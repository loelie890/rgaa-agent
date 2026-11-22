"""Rapport HTML autonome, avant / après, lisible par un humain pressé.

Contraintes tenues volontairement :

* un seul fichier, CSS en ligne, aucune ressource externe, aucun JavaScript ;
* le rapport est **lui-même conforme aux 12 règles** du moteur (c'est testé) :
  ``lang``, titre, hiérarchie de titres, en-têtes de tableau, contrastes,
  listes bien formées, identifiants uniques.
"""

from __future__ import annotations

import datetime as dt
from difflib import SequenceMatcher
from html import escape
from typing import Any

from .audit import RULES

STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 20px 64px; background: #ffffff; color: #1b1f24;
       font: 16px/1.6 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1040px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 6px; }
h2 { font-size: 19px; margin: 34px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #d8dee6; }
h3 { font-size: 15px; margin: 22px 0 8px; }
p, li, td, th { font-size: 15px; }
p { margin: 0 0 10px; }
.lead { color: #4a5560; margin-bottom: 22px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin: 0 0 8px; padding: 0; list-style: none; }
.card { border: 1px solid #d8dee6; border-radius: 10px; padding: 12px 16px; min-width: 150px; }
.card .label { color: #4a5560; font-size: 13px; display: block; }
.card .value { font-size: 21px; font-weight: 700; }
.good { color: #1d6b3a; }
.bad { color: #a01b1b; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 4px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #e2e7ee; vertical-align: top; }
th { background: #f2f5f9; font-size: 14px; }
code { background: #f2f5f9; border-radius: 4px; padding: 1px 5px; font-size: 13px; }
.diff { display: flex; flex-wrap: wrap; gap: 12px; }
.diff section { flex: 1 1 320px; border: 1px solid #d8dee6; border-radius: 8px; padding: 10px 12px; }
.diff h3 { margin: 0 0 6px; font-size: 13px; color: #4a5560; }
pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.55; }
del { background: #fdeaea; color: #8c1616; text-decoration: line-through; }
ins { background: #e6f4ea; color: #14532d; text-decoration: none; }
.note { border-left: 3px solid #d8dee6; padding: 2px 0 2px 12px; color: #4a5560; }
footer { margin-top: 40px; color: #4a5560; font-size: 13px; }
"""


def _diff_pair(before: str, after: str) -> tuple[str, str]:
    """Diff au caractère, échappé, avec ``del`` / ``ins`` sémantiques."""
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    left: list[str] = []
    right: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            fragment = escape(before[i1:i2])
            left.append(fragment)
            right.append(fragment)
        else:
            if i2 > i1:
                left.append(f"<del>{escape(before[i1:i2])}</del>")
            if j2 > j1:
                right.append(f"<ins>{escape(after[j1:j2])}</ins>")
    return "".join(left), "".join(right)


def render_report(
    *,
    baseline: dict[str, Any],
    current: dict[str, Any],
    patches: list[dict[str, Any]],
    findings: list[Any],
    pages: list[str],
    as_of: dt.date,
    mode: str = "replay",
) -> str:
    before = baseline["score"]
    delta = round(current["percent"] - before["percent"], 1)
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    cards = [
        ("Conformité avant", f"{before['percent']} %", "bad" if before["percent"] < 100 else "good"),
        ("Conformité après", f"{current['percent']} %", "good" if current["percent"] >= 100 else "bad"),
        ("Progression", f"{delta:+.1f} pts", "good" if delta > 0 else "bad"),
        ("Violations restantes", str(current["violations"]), "good" if current["violations"] == 0 else "bad"),
        ("Corrections appliquées", str(len(patches)), ""),
        ("Pages auditées", str(current["pages"]), ""),
    ]

    rows = []
    for rule in RULES:
        state_before = "conforme" if rule.id in before["rules_ok"] else "non conforme"
        state_after = "conforme" if rule.id in current["rules_ok"] else "non conforme"
        rows.append(
            "<tr>"
            f"<td>{escape(rule.label)}<br><code>{escape(rule.id)}</code></td>"
            f"<td>{escape(rule.rgpa)}</td>"
            f"<td>{escape(rule.severity)}</td>"
            f"<td>{escape(state_before)}</td>"
            f"<td>{escape(state_after)}</td>"
            "</tr>"
        )

    diffs = []
    for index, patch in enumerate(patches, start=1):
        left, right = _diff_pair(patch.get("before", ""), patch.get("after", ""))
        detail = patch.get("op", "")
        if patch.get("name"):
            detail += f" {patch['name']}"
        if patch.get("value"):
            detail += f' = {patch["value"]}'
        diffs.append(
            f"<h3>Correction {index} · <code>{escape(patch.get('page', ''))}</code> · "
            f"<code>{escape(patch.get('selector', ''))}</code> · {escape(detail)}</h3>"
            '<div class="diff">'
            f'<section><h3>Avant</h3><pre>{left or "(vide)"}</pre></section>'
            f'<section><h3>Après</h3><pre>{right or "(vide)"}</pre></section>'
            "</div>"
        )

    if findings:
        remaining = "<ul>" + "".join(
            f"<li><code>{escape(finding.rule)}</code> ({escape(finding.rgpa)}) sur "
            f"<code>{escape(finding.page)}</code> : {escape(finding.message)}</li>"
            for finding in findings
        ) + "</ul>"
    else:
        remaining = "<p>Aucune : les 12 règles passent sur toutes les pages au moment de la génération.</p>"

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rapport d'accessibilité RGAA 4.1, avant et après corrections</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<h1>Rapport d'accessibilité RGAA 4.1</h1>
<p class="lead">Site de démonstration · {len(pages)} pages auditées · {len(RULES)} règles vérifiées mécaniquement ·
exécution en mode {escape(mode)} · référence {as_of.isoformat()} · généré le {generated}.
Audit, corrections et recalcul du score effectués localement, hors ligne.</p>

<h2>Résultat</h2>
<ul class="cards">
{"".join(f'<li class="card"><span class="label">{escape(label)}</span><span class="value {klass}">{escape(value)}</span></li>' for label, value, klass in cards)}
</ul>
<p class="note">Le score est le rapport entre les contrôles conformes et le total des contrôles (règles × pages).
Il est recalculé depuis le HTML réellement présent sur le disque après chaque correction, et non déclaré.</p>

<h2>Critères vérifiés</h2>
<table>
<thead><tr><th>Critère</th><th>RGAA</th><th>Sévérité</th><th>Avant</th><th>Après</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>

<h2>Corrections appliquées</h2>
{"".join(diffs) if diffs else "<p>Aucune correction appliquée.</p>"}

<h2>Violations restantes</h2>
{remaining}

<h2>Portée et limites</h2>
<p>Ces 12 règles sont vérifiées sur l'arbre HTML : balises, attributs, texte accessible, contraste calculé
depuis les styles en ligne et les blocs de style internes. Ce n'est pas un audit complet des 106 critères du
RGAA 4.1. La pertinence éditoriale d'un texte alternatif, la qualité d'un intitulé de lien, l'accessibilité
d'un contenu dynamique et le rendu réel dans un navigateur restent des vérifications humaines.</p>

<footer>Rapport généré par RGAA Agent. Aucune ressource externe, aucun script, aucune donnée envoyée.</footer>
</main>
</body>
</html>
"""
