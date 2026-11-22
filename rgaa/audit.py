"""Moteur d'audit : 12 règles issues du RGAA 4.1, vérifiées sur l'arbre HTML réel.

Chaque constat porte un sélecteur qui cible l'élément fautif : c'est ce qui rend
la boucle possible — l'agent corrige l'élément désigné, puis l'audit revérifie.

Ce moteur n'est pas un validateur complet du RGAA (106 critères). Les 12 règles
retenues sont celles qui se vérifient mécaniquement et qui couvrent les erreurs
les plus fréquentes d'un site vitrine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .css import (  # noqa: F401 - réexportés pour les tests et les appelants
    contrast_ratio,
    has_direct_text,
    parse_color,
    parse_stylesheets,
    resolve_text_style,
    threshold_for,
)
from .dom import Document, Node, select

SEVERITIES = {"bloquant": 3, "majeur": 2, "mineur": 1}


@dataclass
class Rule:
    id: str
    label: str
    rgpa: str
    severity: str
    check: Callable[[Document], list[tuple[Node, str]]]


@dataclass
class Finding:
    rule: str
    label: str
    rgpa: str
    severity: str
    page: str
    selector: str
    message: str
    evidence: str

    @property
    def id(self) -> str:
        return f"{self.rule}@{self.page}"


def selector_for(node: Node) -> str:
    if node.get("id"):
        return f"{node.tag}#{node.get('id')}"
    classes = node.get("class").split()
    if classes:
        return f"{node.tag}.{classes[0]}"
    return node.tag


def _page_has_doctype(doc: Document) -> bool:
    return bool(doc.doctype)


def _check_lang(doc: Document) -> list[tuple[Node, str]]:
    root = doc.root
    if not (root.get("lang") or root.get("xml:lang")):
        return [(root, "l'élément <html> n'a pas d'attribut lang : la langue de la page n'est pas déclarée")]
    return []


def _check_title(doc: Document) -> list[tuple[Node, str]]:
    titles = select(doc.root, "title")
    if not titles:
        return [(doc.root, "aucun élément <title> : la page n'a pas de titre")]
    if not titles[0].text().strip():
        return [(titles[0], "le titre de la page est vide")]
    return []


def _check_img_alt(doc: Document) -> list[tuple[Node, str]]:
    out = []
    for image in select(doc.root, "img"):
        alt = image.attrs.get("alt")
        decorative = image.get("role") == "presentation" or image.get("aria-hidden") == "true"
        if alt is None:
            out.append((image, "image sans attribut alt : aucun texte alternatif"))
        elif not alt.strip() and not decorative:
            out.append(
                (
                    image,
                    "alt vide sur une image qui n'est pas déclarée décorative "
                    "(ajouter alt=\"\" ET role=\"presentation\", ou décrire l'image)",
                )
            )
    return out


def _check_label(doc: Document) -> list[tuple[Node, str]]:
    skip = {"hidden", "submit", "button", "reset", "image"}
    labels = {label.get("for") for label in select(doc.root, "label") if label.get("for")}
    out = []
    for field in select(doc.root, "input"):
        if field.get("type", "text").lower() in skip:
            continue
        identified = field.get("id") and field.get("id") in labels
        named = field.get("aria-label") or field.get("aria-labelledby") or field.get("title")
        if not identified and not named:
            out.append((field, "champ de formulaire sans étiquette associée (ni <label for>, ni aria-label)"))
    return out


def _accessible_text(node: Node) -> str:
    """Texte effectivement annoncé : on ignore les sous-arbres aria-hidden."""
    if node.tag == "#text":
        return node.data
    if node.get("aria-hidden") == "true":
        return ""
    return "".join(_accessible_text(child) for child in node.children)


def _check_button(doc: Document) -> list[tuple[Node, str]]:
    out = []
    for button in select(doc.root, "button"):
        name = button.get("aria-label") or button.get("title")
        if not (name or _accessible_text(button).strip()):
            out.append((button, "bouton sans intitulé accessible : un lecteur d'écran annonce « bouton »"))
    return out


def _check_link(doc: Document) -> list[tuple[Node, str]]:
    out = []
    for link in select(doc.root, "a"):
        if link.get("aria-label") or link.get("title"):
            continue
        if _accessible_text(link).strip():
            continue
        images = [img for img in link.descendants() if img.tag == "img"]
        if images and any(img.get("alt", "").strip() for img in images):
            continue
        out.append((link, "lien sans intitulé : ni texte, ni alt d'image, ni aria-label"))
    return out


def _check_headings(doc: Document) -> list[tuple[Node, str]]:
    headings = [node for node in [doc.root] + doc.root.descendants() if re.fullmatch(r"h[1-6]", node.tag)]
    if not headings:
        return []
    out = []
    levels = [int(node.tag[1]) for node in headings]
    if levels[0] != 1:
        out.append((headings[0], f"la page commence par un <{headings[0].tag}> au lieu d'un <h1>"))
    for previous, current, node in zip(levels, levels[1:], headings[1:]):
        if current > previous + 1:
            out.append(
                (
                    node,
                    f"saut de niveau dans les titres : <h{previous}> puis <h{current}> "
                    "(un lecteur d'écran perd la hiérarchie)",
                )
            )
    if levels.count(1) > 1:
        out.append((headings[levels.index(1, levels.index(1) + 1)], "plusieurs <h1> sur la même page"))
    return out


def _check_table(doc: Document) -> list[tuple[Node, str]]:
    out = []
    for table in select(doc.root, "table"):
        rows = select(table, "tr")
        if not rows:
            continue
        header_cells = [cell for cell in select(rows[0], "th")]
        if not header_cells:
            out.append((table, "tableau sans cellule d'en-tête <th> : les colonnes ne sont pas annoncées"))
    return out


def _check_iframe(doc: Document) -> list[tuple[Node, str]]:
    out = []
    for frame in select(doc.root, "iframe"):
        if not frame.get("title").strip():
            out.append((frame, "cadre <iframe> sans attribut title : contenu non identifiable"))
    return out


_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def _check_contrast(doc: Document) -> list[tuple[Node, str]]:
    """Critère 3.2 : ratio calculé sur les couleurs réellement applicables.

    Les couleurs viennent du style en ligne ou des blocs ``<style>`` (cascade
    simplifiée, héritage du fond depuis les ancêtres), jamais d'une feuille
    externe non téléchargée.
    """
    rules = parse_stylesheets(doc)
    out: list[tuple[Node, str]] = []
    skipped = {"#text", "style", "script", "title", "head", "meta", "link"}
    for node in [doc.root] + doc.root.descendants():
        if node.tag in skipped or not has_direct_text(node):
            continue
        style = resolve_text_style(doc, node, rules)
        foreground = parse_color(style["color"])
        background = parse_color(style["background"])
        if not foreground or not background:
            continue
        ratio = contrast_ratio(foreground, background)
        threshold = threshold_for(style["font_size"], style["bold"])
        if ratio < threshold:
            out.append(
                (
                    node,
                    f"contraste insuffisant : {ratio:.2f}:1 pour un seuil de {threshold}:1 "
                    f"(texte {style['color']} sur fond {style['background']}, couleur issue de la {style['source']})",
                )
            )
    return out


def _check_duplicate_id(doc: Document) -> list[tuple[Node, str]]:
    seen: dict[str, Node] = {}
    out = []
    for node in [doc.root] + doc.root.descendants():
        ident = node.get("id")
        if not ident:
            continue
        if ident in seen:
            out.append((node, f"identifiant « {ident} » déjà utilisé plus haut dans la page"))
        else:
            seen[ident] = node
    return out


def _check_lists(doc: Document) -> list[tuple[Node, str]]:
    out = []
    for liste in select(doc.root, "ul") + select(doc.root, "ol"):
        for child in liste.elements():
            if child.tag not in {"li", "ul", "ol", "template"}:
                out.append(
                    (
                        child,
                        f"<{child.tag}> enfant direct d'une liste : structure de liste invalide",
                        f"{selector_for(liste)} > {child.tag}",
                    )
                )
    return out


RULES: list[Rule] = [
    Rule("lang", "Langue de la page déclarée", "8.3", "bloquant", _check_lang),
    Rule("title", "Titre de page présent et renseigné", "8.6", "bloquant", _check_title),
    Rule("img-alt", "Images avec alternative pertinente", "1.1", "bloquant", _check_img_alt),
    Rule("link-name", "Intitulé de lien explicite", "6.1", "majeur", _check_link),
    Rule("button-name", "Intitulé de bouton", "11.9", "majeur", _check_button),
    Rule("label", "Étiquette de champ de formulaire", "11.1", "bloquant", _check_label),
    Rule("headings", "Hiérarchie des titres", "9.1", "majeur", _check_headings),
    Rule("table-header", "En-têtes de colonnes", "5.6", "majeur", _check_table),
    Rule("iframe-title", "Cadre avec titre", "2.1", "majeur", _check_iframe),
    Rule("contrast", "Contraste des textes", "3.2", "majeur", _check_contrast),
    Rule("duplicate-id", "Identifiants uniques", "8.2", "mineur", _check_duplicate_id),
    Rule("list-structure", "Structure de liste valide", "9.3", "mineur", _check_lists),
]

RULE_BY_ID = {rule.id: rule for rule in RULES}


def audit_page(page: str, document: Document) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES:
        for node, message, *rest in rule.check(document):
            findings.append(
                Finding(
                    rule=rule.id,
                    label=rule.label,
                    rgpa=rule.rgpa,
                    severity=rule.severity,
                    page=page,
                    selector=rest[0] if rest else selector_for(node),
                    message=message,
                    evidence=node.snippet(),
                )
            )
    findings.sort(key=lambda f: (-SEVERITIES[f.severity], f.rule, f.page))
    return findings


def audit_site(pages: dict[str, Document]) -> list[Finding]:
    findings: list[Finding] = []
    for page, document in sorted(pages.items()):
        findings.extend(audit_page(page, document))
    return findings


GRADES = (
    (95.0, "A", "quasi conforme"),
    (85.0, "B", "bonne conformité"),
    (70.0, "C", "conformité partielle"),
    (50.0, "D", "insuffisant"),
)


def grade(percent: float) -> dict:
    """Note lisible d'un score : une lettre, un libellé, le seuil atteint."""
    for threshold, letter, label in GRADES:
        if percent >= threshold:
            return {"letter": letter, "label": label, "threshold": threshold}
    return {"letter": "E", "label": "critique", "threshold": 0.0}


def score(pages: dict[str, Document]) -> dict:
    """Conformité par règle et par page — le chiffre qui bouge quand l'agent corrige."""
    findings = audit_site(pages)
    violated = {(finding.rule, finding.page) for finding in findings}
    checks = [(rule.id, page) for rule in RULES for page in pages]
    conform = [check for check in checks if check not in violated]
    rules_ok = [rule.id for rule in RULES if all((rule.id, page) not in violated for page in pages)]
    rules_ko = [rule.id for rule in RULES if rule.id not in rules_ok]
    percent = round(100 * len(conform) / len(checks), 1) if checks else 100.0
    return {
        "pages": len(pages),
        "rules": len(RULES),
        "checks": len(checks),
        "conform": len(conform),
        "percent": percent,
        "grade": grade(percent),
        "violations": len(findings),
        "rules_ok": rules_ok,
        "rules_ko": rules_ko,
        "by_severity": {
            severity: sum(1 for finding in findings if finding.severity == severity) for severity in SEVERITIES
        },
    }

