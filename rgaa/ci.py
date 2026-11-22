"""Mode intégration continue : audit, corrections déterministes, diff, code de sortie.

Sans modèle, sans cassette. Le mode CI applique les corrections mécaniques que la
table ci-dessous sait produire, relance l'audit jusqu'à stabilité, écrit un diff
unifié applicable avec ``git apply``, et sort en erreur si le score reste sous le
seuil demandé.

Deux corrections ne sont pas devinables mécaniquement : une description d'image
et un intitulé de bouton. Le mode CI les produit **provisoirement** (titre
existant, nom de fichier, attribut ``title``) et les marque ``review`` dans le
résultat. Le README le dit, et le rapport les liste.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Callable

from .audit import RULES, audit_site, score, selector_for
from .css import propose_compliant, resolve_text_style, threshold_for
from .dom import Document, Node, parse, select

EXCLUDED_DIRS = {".git", "node_modules", "runs", "data", "__pycache__", ".venv", "venv", "deliverables"}
MAX_ROUNDS = 4


def site_pages(site: Path) -> dict[str, Path]:
    site = Path(site).resolve()
    pages: dict[str, Path] = {}
    for path in sorted(site.rglob("*.htm*")):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(site).parts[:-1]):
            continue
        pages[path.name] = path
    return pages


def humanize(value: str) -> str:
    stem = Path(value.split("?")[0]).stem
    words = re.sub(r"[-_]+", " ", stem).strip()
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", words)
    return words[:1].upper() + words[1:] if words else "Illustration"


def _accessible_text(node: Node) -> str:
    if node.tag == "#text":
        return node.data
    if node.get("aria-hidden") == "true":
        return ""
    return "".join(_accessible_text(child) for child in node.children)


def _ancestor(node: Node, tag: str) -> Node | None:
    current = node.parent
    while current is not None:
        if current.tag == tag:
            return current
        current = current.parent
    return None


# --------------------------------------------------------------------------- #
# Correcteurs : (document, nœud) -> description, ou None si rien n'a été changé
# --------------------------------------------------------------------------- #
def fix_lang(doc: Document, node: Node, message: str, lang: str) -> str | None:
    if node.get("lang"):
        return None
    node.attrs["lang"] = lang
    return f'lang="{lang}" sur <html>'


def fix_title(doc: Document, node: Node, message: str, lang: str) -> str | None:
    if node.text().strip():
        return None
    headings = select(doc.root, "h1") or select(doc.root, "h2")
    text = " ".join(headings[0].text().split()) if headings else "Page sans titre"
    node.children = [Node("#text", data=text)]
    node.children[0].parent = node
    return f'titre de page déduit du premier titre : "{text}"'


def fix_img_alt(doc: Document, node: Node, message: str, lang: str) -> str | None:
    alt = node.attrs.get("alt")
    if alt is not None and alt.strip():
        return None
    if alt is not None and node.get("role") == "presentation":
        return None

    link = _ancestor(node, "a")
    if link is not None and (_accessible_text(link).strip() or link.get("aria-label")):
        node.attrs["alt"] = ""
        node.attrs["role"] = "presentation"
        return "image décorative à l'intérieur d'un lien déjà nommé (alt vide + role=presentation)"

    source = node.get("title") or node.get("data-alt") or node.get("src", "")
    # Un pictogramme de logo ou d'icône est décoratif par nature : le nommer ne sert à rien.
    if re.search(r"(^|[/_-])(logo|icone|icon|picto)", str(source).lower()):
        node.attrs["alt"] = ""
        node.attrs["role"] = "presentation"
        return "pictogramme déclaré décoratif (alt vide + role=presentation)"
    description = humanize(source) if source else "Illustration"
    node.attrs["alt"] = description
    node.attrs.pop("role", None)
    return f'alt provisoire "{description}" (review : description humaine attendue)'


def fix_link_name(doc: Document, node: Node, message: str, lang: str) -> str | None:
    if node.get("aria-label") or node.get("title") or _accessible_text(node).strip():
        return None
    target = node.get("href", "")
    image = next((child for child in node.descendants() if child.tag == "img"), None)
    label = humanize(target) if target and target != "#" else humanize(image.get("src", "") if image else "")
    node.attrs["aria-label"] = f"Lien vers {label or 'la page'}"
    return f'aria-label="{node.attrs["aria-label"]}"'


def fix_button_name(doc: Document, node: Node, message: str, lang: str) -> str | None:
    if node.get("aria-label") or node.get("title") or _accessible_text(node).strip():
        return None
    label = node.get("data-label") or "Action"
    node.attrs["aria-label"] = label
    return f'aria-label="{label}" (review : intitulé visible attendu)'


def fix_label(doc: Document, node: Node, message: str, lang: str) -> str | None:
    field_id = node.get("id") or f"champ-{abs(hash(node)) % 1000}"
    node.attrs.setdefault("id", field_id)
    text = node.get("placeholder") or humanize(field_id)
    label = Node("label", {"for": field_id})
    label.children = [Node("#text", data=text)]
    label.children[0].parent = label
    parent = node.parent
    if parent is None:
        return None
    parent.insert(label, parent.children.index(node))
    return f'<label for="{field_id}">{text}</label> inséré avant le champ'


def fix_headings(doc: Document, node: Node, message: str, lang: str) -> str | None:
    headings = [entry for entry in [doc.root] + doc.root.descendants() if re.fullmatch(r"h[1-6]", entry.tag)]
    levels = [int(entry.tag[1]) for entry in headings]
    index = headings.index(node)
    if index == 0 and node.tag != "h1":
        node.tag = "h1"
        return "<%s> promu en h1" % node.tag
    if index > 0 and levels[index] > levels[index - 1] + 1:
        target = f"h{levels[index - 1] + 1}"
        previous = node.tag
        node.tag = target
        return f"<{previous}> rétrogradé en <{target}> pour rétablir la hiérarchie"
    if levels.count(1) > 1 and node.tag == "h1":
        node.tag = "h2"
        return "<h1> en double rétrogradé en <h2>"
    return None


def fix_table_header(doc: Document, node: Node, message: str, lang: str) -> str | None:
    rows = select(node, "tr")
    if not rows:
        return None
    cells = [cell for cell in rows[0].elements() if cell.tag == "td"]
    if not cells:
        return None
    for cell in cells:
        cell.tag = "th"
    return f"{len(cells)} cellule(s) de la première ligne converties en <th>"


def fix_iframe_title(doc: Document, node: Node, message: str, lang: str) -> str | None:
    if node.get("title", "").strip():
        return None
    source = node.get("src") or node.get("data-src") or ""
    host = re.sub(r"^https?://", "", source).split("/")[0] or "contenu embarqué"
    node.attrs["title"] = f"Contenu embarqué depuis {host}"
    return f'title="{node.attrs["title"]}"'


def fix_contrast(doc: Document, node: Node, message: str, lang: str) -> str | None:
    style = resolve_text_style(doc, node)
    target = threshold_for(style["font_size"], style["bold"])
    proposal = propose_compliant(style["color"], style["background"], target)
    if not proposal["changed"]:
        return None
    declarations = [chunk.strip() for chunk in node.get("style").split(";") if chunk.strip() and not chunk.strip().lower().startswith("color")]
    declarations.append(f"color:{proposal['color']}")
    node.attrs["style"] = ";".join(declarations)
    return f"couleur {proposal['original']} -> {proposal['color']} (contraste {proposal['original_ratio']}:1 -> {proposal['ratio']}:1)"


def fix_duplicate_id(doc: Document, node: Node, message: str, lang: str) -> str | None:
    ident = node.get("id")
    if not ident:
        return None
    candidate = f"{ident}-2"
    counter = 2
    taken = {entry.get("id") for entry in [doc.root] + doc.root.descendants()}
    while candidate in taken:
        counter += 1
        candidate = f"{ident}-{counter}"
    node.attrs["id"] = candidate
    return f'id "{ident}" renommé "{candidate}"'


def fix_list_structure(doc: Document, node: Node, message: str, lang: str) -> str | None:
    if node.tag in {"li", "ul", "ol"}:
        return None
    previous = node.tag
    node.tag = "li"
    return f"<{previous}> converti en <li>"


FIXERS: dict[str, Callable[[Document, Node, str, str], str | None]] = {
    "lang": fix_lang,
    "title": fix_title,
    "img-alt": fix_img_alt,
    "link-name": fix_link_name,
    "button-name": fix_button_name,
    "label": fix_label,
    "headings": fix_headings,
    "table-header": fix_table_header,
    "iframe-title": fix_iframe_title,
    "contrast": fix_contrast,
    "duplicate-id": fix_duplicate_id,
    "list-structure": fix_list_structure,
}

REVIEW_RULES = {"img-alt", "button-name", "link-name"}


def _fix_page(page: str, document: Document, lang: str, patches: list[dict[str, Any]]) -> int:
    applied = 0
    for _ in range(MAX_ROUNDS):
        changed = 0
        seen: set[int] = set()
        for rule in RULES:
            fixer = FIXERS.get(rule.id)
            if fixer is None:
                continue
            for node, message, *rest in rule.check(document):
                if id(node) in seen:
                    continue
                before = node.snippet(240)
                description = fixer(document, node, message, lang)
                if not description:
                    continue
                seen.add(id(node))
                changed += 1
                patches.append(
                    {
                        "page": page,
                        "selector": rest[0] if rest else selector_for(node),
                        "op": description,
                        "before": before,
                        "after": node.snippet(240),
                        "review": rule.id in REVIEW_RULES,
                    }
                )
        applied += changed
        if not changed:
            break
    return applied


def run_ci(
    site: Path,
    *,
    min_score: float = 100.0,
    write: bool = False,
    diff_path: Path | None = None,
    report_path: Path | None = None,
    lang: str = "fr",
    vision: dict[str, Any] | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    pages = site_pages(Path(site))
    if not pages:
        raise FileNotFoundError(f"aucune page HTML trouvée dans {site}")

    documents = {name: parse(path.read_text(encoding="utf-8")) for name, path in pages.items()}
    originals = {name: path.read_text(encoding="utf-8") for name, path in pages.items()}
    baseline = score({name: parse(markup) for name, markup in originals.items()})

    patches: list[dict[str, Any]] = []
    for name, document in documents.items():
        _fix_page(name, document, lang, patches)

    # Passe vision : elle ne remplace pas les corrections mécaniques, elle les complète
    # sur ce que le HTML ne peut pas dire (alternative absente, générique, texte dans l'image).
    vision_report: dict[str, Any] = {"available": False, "images": 0, "findings": 0, "fixes": 0}
    if vision and vision.get("base_url") and vision.get("model"):
        from .vision_audit import apply_to_documents, audit_documents

        vision_report = audit_documents(documents, Path(site), vision, base_url=base_url)
        vision_patches = apply_to_documents(documents, vision_report.get("findings", []))
        # Une alternative écrite par le modèle remplace le correctif provisoire du même élément.
        vision_keys = {(patch["page"], patch["selector"]) for patch in vision_patches}
        patches = [
            patch
            for patch in patches
            if not (patch.get("review") and (patch["page"], patch["selector"]) in vision_keys)
        ]
        patches.extend(vision_patches)
        vision_report = {
            "available": vision_report["available"],
            "model": vision_report.get("model", ""),
            "images": len(vision_report.get("images", [])),
            "findings": len(vision_report.get("findings", [])),
            "fixes": len(vision_patches),
            "skipped": len(vision_report.get("skipped", [])),
            "details": vision_report.get("findings", []),
            "samples": [
                {
                    "src": item.get("src", ""),
                    "selector": item.get("selector", ""),
                    "brut": str(item.get("brut") or item.get("description") or "")[:200],
                    "usable": item.get("usable"),
                    "reason": str(item.get("reason") or "")[:120],
                    "origin": item.get("origin", ""),
                }
                for item in vision_report.get("images", [])[:6]
            ],
        }

    serialized = {name: document.serialize() for name, document in documents.items()}
    current = score({name: parse(markup) for name, markup in serialized.items()})
    findings = audit_site({name: parse(markup) for name, markup in serialized.items()})

    diff_text = ""
    for name in sorted(pages):
        if originals[name] == serialized[name]:
            continue
        diff_text += "".join(
            difflib.unified_diff(
                originals[name].splitlines(keepends=True),
                serialized[name].splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
                n=3,
            )
        )
        if diff_text and not diff_text.endswith("\n"):
            diff_text += "\n"

    if diff_path:
        Path(diff_path).parent.mkdir(parents=True, exist_ok=True)
        Path(diff_path).write_text(diff_text, encoding="utf-8")

    if write:
        for name, markup in serialized.items():
            pages[name].write_text(markup, encoding="utf-8")

    if report_path:
        from .report import render_report

        markup = render_report(
            baseline={"score": baseline},
            current=current,
            patches=[
                {**patch, "op": patch["op"], "name": "", "value": ""} for patch in patches
            ],
            findings=findings,
            pages=sorted(pages),
            as_of=__import__("datetime").date.today(),
            mode="ci",
        )
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(markup, encoding="utf-8")

    passed = current["percent"] >= float(min_score)
    return {
        "site": str(Path(site).resolve()),
        "pages": sorted(pages),
        "baseline": baseline,
        "score": current,
        "patches": patches,
        "review": [patch for patch in patches if patch.get("review")],
        "findings": [
            {"rule": finding.rule, "page": finding.page, "selector": finding.selector, "message": finding.message}
            for finding in findings
        ],
        "diff": diff_text,
        "diff_path": str(diff_path) if diff_path else "",
        "report_path": str(report_path) if report_path else "",
        "min_score": float(min_score),
        "passed": passed,
        "vision": vision_report,
        "exit_code": 0 if passed else 1,
    }
