"""Ce que le rendu réel ajoute à l'audit.

Chaque constat vient d'une mesure faite par le navigateur : contraste calculé sur
le style effectif, intitulé accessible recalculé, contenu injecté par JavaScript.
La sortie suit la même forme que l'audit statique (`rule`, `severity`, `page`,
`selector`, `message`) pour se fondre dans les rapports existants.
"""

from __future__ import annotations

from typing import Any

BLOCKING = "bloquant"
MAJOR = "majeur"
MINOR = "mineur"

# Seuils WCAG : 4,5:1 en texte courant, 3:1 en grand texte (>= 24 px, ou 19 px gras).
LARGE_PX = 24.0
LARGE_BOLD_PX = 18.66


def _finding(rule: str, criterion: str, severity: str, selector: str, message: str, **extra: Any) -> dict[str, Any]:
    row = {
        "rule": rule,
        "criterion": criterion,
        "severity": severity,
        "selector": selector,
        "message": message,
        "source": "navigateur",
    }
    row.update(extra)
    return row


def analyse(report: dict[str, Any], page: str = "page") -> dict[str, Any]:
    """Transforme le rapport de la sonde en constats RGAA."""
    findings: list[dict[str, Any]] = []
    if not report:
        return {"page": page, "findings": [], "counts": {}, "available": False, "js": {}}

    # 3.2 contraste, mesuré sur le style calculé
    for entry in report.get("contrasts", []):
        size = float(entry.get("size") or 16)
        bold = bool(entry.get("bold"))
        required = 3.0 if size >= LARGE_PX or (bold and size >= LARGE_BOLD_PX) else 4.5
        ratio = float(entry.get("ratio") or 0)
        if ratio and ratio < required:
            findings.append(
                _finding(
                    "browser-contraste",
                    "3.2",
                    BLOCKING if required >= 4.5 else MAJOR,
                    entry.get("selector", ""),
                    f"contraste réel {ratio:.2f}:1, minimum {required:.1f}:1 pour {size:.0f} px",
                    ratio=ratio,
                    text=entry.get("text", ""),
                )
            )

    # 1.1 et 1.2 images : alternative absente, ou décorative mal déclarée
    for image in report.get("images", []):
        alt = image.get("alt")
        role = (image.get("role") or "").lower()
        decorative = alt == "" and role == "presentation"
        if alt is None and not decorative:
            findings.append(
                _finding(
                    "browser-alt-absente", "1.1", BLOCKING, image.get("selector", ""),
                    f"image sans alternative dans le DOM rendu ({image.get('src') or 'sans source'})",
                )
            )
        elif alt == "" and not decorative and (image.get("width") or 0) > 32 and (image.get("height") or 0) > 32:
            findings.append(
                _finding(
                    "browser-alt-vide", "1.3", MAJOR, image.get("selector", ""),
                    "alternative vide sur une image de taille visible, non déclarée décorative",
                )
            )

    # 2.1 cadre sans titre
    for frame in report.get("iframes", []):
        if not (frame.get("title") or "").strip():
            findings.append(
                _finding("browser-cadre-sans-titre", "2.1", BLOCKING, frame.get("selector", ""), "cadre sans intitulé")
            )

    # 6.1 lien sans intitulé accessible
    for link in report.get("links", []):
        name = (link.get("text") or "").strip() or (link.get("aria") or "").strip() or (link.get("title") or "").strip()
        if not name:
            findings.append(
                _finding(
                    "browser-lien-sans-intitule", "6.1", BLOCKING, link.get("selector", ""),
                    f"lien sans intitulé exploitable ({link.get('href')})",
                )
            )

    # 11.1 et 11.2 champs de formulaire
    for control in report.get("controls", []):
        if control.get("type") in {"hidden", "submit", "button", "reset"}:
            continue
        if not (control.get("label") or control.get("aria") or control.get("title")):
            findings.append(
                _finding(
                    "browser-champ-sans-etiquette", "11.1", BLOCKING, control.get("selector", ""),
                    f"champ sans étiquette dans le DOM rendu ({control.get('type')})",
                )
            )

    # 9.1 hiérarchie des titres, telle que le rendu la produit
    previous = 0
    for heading in report.get("headings", []):
        level = int(heading.get("level") or 0)
        if previous and level > previous + 1:
            findings.append(
                _finding(
                    "browser-titre-saute", "9.1", MAJOR, f"h{level}",
                    f"h{previous} suivi de h{level} dans le DOM rendu : {heading.get('text', '')}",
                )
            )
        previous = level

    # 8.3 8.4 8.5 langue et titre du document
    lang = (report.get("lang") or "").strip()
    if not lang:
        findings.append(_finding("browser-langue-absente", "8.3", BLOCKING, "html", "langue du document absente"))
    elif len(lang) < 2 or len(lang) > 12:
        findings.append(_finding("browser-langue-invalide", "8.4", MAJOR, "html", f"code de langue douteux : {lang}"))
    if not (report.get("title") or "").strip():
        findings.append(_finding("browser-titre-absent", "8.5", BLOCKING, "head", "titre de page absent"))

    # Contenu réellement présentable : ce que JavaScript ajoute, et qui n'existe
    # pas dans le fichier source.
    js = {"text_length": report.get("jsText"), "landmarks": report.get("landmarks", {})}
    if not report.get("landmarks", {}).get("main"):
        findings.append(
            _finding("browser-pas-de-main", "12.6", MINOR, "body", "aucune zone principale déclarée dans le rendu")
        )
    for hidden in report.get("hiddenFocusable", []):
        findings.append(
            _finding(
                "browser-focus-cache", "10.7", MAJOR, hidden.get("selector", ""),
                "élément focalisable masqué par aria-hidden",
            )
        )

    counts: dict[str, int] = {}
    for row in findings:
        counts[row["severity"]] = counts.get(row["severity"], 0) + 1
    return {"page": page, "findings": findings, "counts": counts, "available": True, "js": js}


def summary(result: dict[str, Any]) -> str:
    if not result.get("available"):
        return "rendu navigateur indisponible"
    counts = result.get("counts", {})
    total = sum(counts.values())
    parts = [f"{total} constat(s) dans le DOM rendu"]
    for severity in (BLOCKING, MAJOR, MINOR):
        if counts.get(severity):
            parts.append(f"{counts[severity]} {severity}")
    return " · ".join(parts)
