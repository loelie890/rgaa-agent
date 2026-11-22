"""Les 106 critères RGAA 4.1, et ce que cet agent en fait.

Le référentiel compte 106 critères répartis en 13 thématiques. En vérifier 106
demanderait un rendu, un lecteur d'écran et un jugement éditorial. Ce module dit
exactement, critère par critère, lequel est corrigé mécaniquement, lequel est
seulement détecté, et lequel reste à un humain. Aucune prétention, un tableau.
"""

from __future__ import annotations

from typing import Any

THEMES = (
    (1, "Images", 9),
    (2, "Cadres", 2),
    (3, "Couleurs", 3),
    (4, "Multimédia", 13),
    (5, "Tableaux", 8),
    (6, "Liens", 2),
    (7, "Scripts", 5),
    (8, "Éléments obligatoires", 10),
    (9, "Structuration de l'information", 4),
    (10, "Présentation de l'information", 14),
    (11, "Formulaires", 13),
    (12, "Navigation", 11),
    (13, "Consultation", 12),
)

# "corrigé" : l'agent détecte et écrit la correction.
# "détecté" : l'agent signale, la décision reste humaine.
CORRECTED = {
    "1.1": "alternative textuelle ajoutée sur les images porteuses d'information",
    "1.2": "alternative vide et role=presentation sur les images décoratives",
    "1.3": "alternative complétée quand elle est vide ou générique",
    "2.1": "titre ajouté aux cadres",
    "3.2": "teinte conforme la plus proche, contraste recalculé",
    "5.1": "en-têtes de colonne et de ligne, portée déclarée",
    "6.1": "intitulé de lien explicite, aria-label en dernier recours",
    "8.3": "langue déclarée sur html",
    "8.5": "titre de page présent et unique",
    "9.1": "hiérarchie de titres sans saut de niveau",
    "11.1": "étiquette associée au champ",
    "11.2": "intitulé de bouton explicite",
}

DETECTED = {
    "1.4": "image utilisée comme bouton ou lien : alternative à valider",
    "1.6": "description détaillée nécessaire sur les images complexes",
    "1.7": "description d'image complexe, contenu à écrire",
    "2.2": "contenu du cadre à décrire",
    "3.1": "information donnée par la couleur seule, repérage seulement",
    "7.1": "composant piloté par JavaScript repéré, comportement à valider",
    "7.3": "script qui prend le focus, signalé",
    "7.5": "message de statut non annoncé, détecté par attribut",
    "8.4": "code de langue douteux, signalé",
    "8.6": "titre de page pas assez explicite, signalé sans réécriture",
    "8.9": "balisage non valide, détecté sans réparation",
    "9.2": "structure du document cohérente : plan de titres proposé",
    "10.7": "indication de focus masquée, détectée dans le rendu",
    "11.5": "regroupement de champs, signalé",
    "12.6": "absence de zone principale, signalée",
    "12.7": "lien d'évitement absent, signalé",
    "13.1": "ouverture de nouvelle fenêtre non annoncée, détectée",
}

HUMAN = "jugement humain ou rendu assistif, hors périmètre outillé"


def criteria() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, label, count in THEMES:
        for index in range(1, count + 1):
            ident = f"{number}.{index}"
            if ident in CORRECTED:
                status, detail = "corrigé", CORRECTED[ident]
            elif ident in DETECTED:
                status, detail = "détecté", DETECTED[ident]
            else:
                status, detail = "humain", HUMAN
            rows.append({"criterion": ident, "theme": label, "theme_number": number, "status": status, "detail": detail})
    return rows


def matrix() -> dict[str, Any]:
    rows = criteria()
    counts = {"corrigé": 0, "détecté": 0, "humain": 0}
    for row in rows:
        counts[row["status"]] += 1
    total = len(rows)
    outillés = counts["corrigé"] + counts["détecté"]
    themes = []
    for number, label, count in THEMES:
        subset = [row for row in rows if row["theme_number"] == number]
        themes.append(
            {
                "theme": label,
                "criteria": count,
                "corrigés": sum(1 for row in subset if row["status"] == "corrigé"),
                "détectés": sum(1 for row in subset if row["status"] == "détecté"),
            }
        )
    return {
        "total": total,
        "counts": counts,
        "outillés": outillés,
        "share": round(outillés / total * 100, 1) if total else 0.0,
        "themes": themes,
        "criteria": rows,
    }


def check_total() -> int:
    return sum(count for _, _, count in THEMES)


def render_text(data: dict[str, Any] | None = None) -> str:
    data = data or matrix()
    lines = [
        f"{data['total']} critères RGAA 4.1 · {data['outillés']} outillés "
        f"({data['counts']['corrigé']} corrigés, {data['counts']['détecté']} détectés) · "
        f"{data['counts']['humain']} à un humain · {data['share']} %",
        "",
        f"{'thématique':32} {'critères':>8} {'corrigés':>9} {'détectés':>9}",
    ]
    for theme in data["themes"]:
        lines.append(
            f"{theme['theme'][:32]:32} {theme['criteria']:>8} {theme['corrigés']:>9} {theme['détectés']:>9}"
        )
    lines.append("")
    lines.append("Ce qui est corrigé mécaniquement :")
    for row in data["criteria"]:
        if row["status"] == "corrigé":
            lines.append(f"  {row['criterion']:<5} {row['detail']}")
    lines.append("")
    lines.append("Ce qui est seulement détecté :")
    for row in data["criteria"]:
        if row["status"] == "détecté":
            lines.append(f"  {row['criterion']:<5} {row['detail']}")
    return "\n".join(lines)
