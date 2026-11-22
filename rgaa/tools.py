"""Outils de l'agent RGAA : lecture du site, audit, requêtes HTML, patchs, rapport.

Les patchs modifient réellement les fichiers HTML du bac à sable, et l'audit
recalcule vraiment le score après chaque correction : rien n'est déclaré.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .audit import RULES, SEVERITIES, audit_site, score
from .css import propose_compliant
from .dom import Document, Node, apply_patch, parse, select
from .kernel import Ctx, Registry, ToolError
from .report import render_report
from .vision import describe_image

PATCH_LOG = "rgaa-patches.json"
BASELINE = "rgaa-baseline.json"


def _site_pages(ctx: Ctx) -> list[Path]:
    pages = []
    for path in sorted(ctx.sandbox.root.rglob("*.htm*")):
        rel = path.relative_to(ctx.sandbox.root)
        if rel.parts and rel.parts[0] in {"deliverables", "alerts"}:
            continue
        pages.append(path)
    return pages


def _page_path(ctx: Ctx, page: str) -> Path:
    target = ctx.sandbox.resolve(page)
    if not target.is_file():
        raise ToolError(f"page introuvable : {page} — pages disponibles : {', '.join(p.name for p in _site_pages(ctx))}")
    if target.suffix.lower() not in {".html", ".htm"}:
        raise ToolError(f"ce n'est pas une page HTML : {page}")
    return target


def _load(ctx: Ctx, page: str | None = None) -> dict[str, Document]:
    paths = [_page_path(ctx, page)] if page else _site_pages(ctx)
    if not paths:
        raise ToolError("aucune page HTML dans le site")
    return {path.name: parse(path.read_text(encoding="utf-8")) for path in paths}


def _save(ctx: Ctx, page: str, document: Document) -> None:
    _page_path(ctx, page).write_text(document.serialize(), encoding="utf-8")


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _baseline(ctx: Ctx) -> dict[str, Any]:
    """Score d'avant les corrections, capturé à la première lecture du site."""
    path = ctx.sandbox.root / BASELINE
    data = _read_json(path, None)
    if data is None:
        data = {
            "captured_at": ctx.as_of.isoformat(),
            "score": score(_load(ctx)),
            "findings": [finding.__dict__ for finding in audit_site(_load(ctx))],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def build_registry(reg: Registry, ctx: Ctx) -> Registry:
    @reg.tool(
        "skill_recall",
        "Relit les procédures apprises sur un sujet (accessibilité, correction, sélecteurs) avant d'agir.",
        required=("topic",),
        optional={"limit": 3},
    )
    def skill_recall(topic: str, limit: int = 3) -> dict[str, Any]:
        found = ctx.skills.recall(topic, int(limit))
        return {"procedures": found, "found": len(found)}

    @reg.tool(
        "skill_write",
        "Écrit une procédure réutilisable après une erreur ou une découverte coûteuse. Relue aux runs suivants.",
        required=("name", "content"),
    )
    def skill_write(name: str, content: str) -> dict[str, Any]:
        if len(content.strip()) < 20:
            raise ToolError("procédure trop courte : décrire le symptôme, la cause et la règle")
        return ctx.skills.write(name, content)

    @reg.tool("site_list", "Liste les pages HTML du site avec leur taille.", optional={})
    def site_list() -> dict[str, Any]:
        pages = _site_pages(ctx)
        return {
            "count": len(pages),
            "pages": [{"name": path.name, "bytes": path.stat().st_size} for path in pages],
        }

    @reg.tool(
        "audit_run",
        "Exécute les 12 règles RGAA sur une page (ou tout le site) et renvoie les constats avec un sélecteur ciblant chaque élément fautif.",
        optional={"page": "", "severity": ""},
    )
    def audit_run(page: str = "", severity: str = "") -> dict[str, Any]:
        documents = _load(ctx, page or None)
        findings = audit_site(documents)
        if severity:
            if severity not in SEVERITIES:
                raise ToolError(f"severity inconnue : {severity!r} — valeurs : {', '.join(SEVERITIES)}")
            findings = [finding for finding in findings if finding.severity == severity]
        summary = score(documents)
        return {
            "page": page or "tout le site",
            "violations": len(findings),
            "score": summary,
            "findings": [
                {
                    "rule": finding.rule,
                    "label": finding.label,
                    "rgpa": finding.rgpa,
                    "severity": finding.severity,
                    "page": finding.page,
                    "selector": finding.selector,
                    "message": finding.message,
                    "evidence": finding.evidence,
                }
                for finding in findings
            ],
        }

    @reg.tool("audit_score", "Donne le score de conformité courant (règles, contrôles, violations) sans détail.", optional={})
    def audit_score() -> dict[str, Any]:
        documents = _load(ctx)
        return {"score": score(documents), "baseline": _baseline(ctx)["score"]}

    @reg.tool(
        "html_query",
        "Inspecte des éléments : renvoie le HTML, le texte et les attributs pour un sélecteur donné.",
        required=("page", "selector"),
        optional={"limit": 5},
    )
    def html_query(page: str, selector: str, limit: int = 5) -> dict[str, Any]:
        document = _load(ctx, page)[Path(page).name]
        nodes = select(document.root, selector)
        if not nodes:
            raise ToolError(f"sélecteur sans correspondance sur {page} : {selector!r}")
        return {
            "page": page,
            "selector": selector,
            "count": len(nodes),
            "matches": [
                {
                    "tag": node.tag,
                    "text": " ".join(node.text().split())[:160],
                    "attrs": node.attrs,
                    "html": node.snippet(220),
                }
                for node in nodes[: int(limit)]
            ],
        }

    @reg.tool(
        "patch_html",
        "Applique une correction réelle à une page. L'audit est recalculé après coup et renvoie les violations restantes.",
        required=("page", "selector", "op"),
        optional={"name": "", "value": ""},
    )
    def patch_html(page: str, selector: str, op: str, name: str = "", value: str = "") -> dict[str, Any]:
        _baseline(ctx)  # capture l'état d'origine avant la première correction
        document = _load(ctx, page)[Path(page).name]
        try:
            result = apply_patch(document, selector, op, name=name, value=value)
        except Exception as exc:  # noqa: BLE001 - devient une observation pour l'agent
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc
        _save(ctx, page, document)

        log_path = ctx.sandbox.root / PATCH_LOG
        log = _read_json(log_path, [])
        log.append(
            {
                "page": page,
                "selector": selector,
                "op": op,
                "name": name,
                "value": value,
                "changed": result["changed"],
                "before": result["before"],
                "after": result["after"],
            }
        )
        log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

        remaining = [finding for finding in audit_site(_load(ctx)) if finding.page == Path(page).name]
        return {
            **result,
            "page": page,
            "remaining_on_page": len(remaining),
            "remaining_rules": sorted({finding.rule for finding in remaining}),
        }

    @reg.tool(
        "report_render",
        "Génère le rapport markdown avant/après depuis le score initial capturé et les corrections réellement appliquées.",
        optional={"name": "audit-rgaa.md"},
    )
    def report_render(name: str = "audit-rgaa.md") -> dict[str, Any]:
        baseline = _baseline(ctx)
        documents = _load(ctx)
        current = score(documents)
        patches = _read_json(ctx.sandbox.root / PATCH_LOG, [])
        findings = audit_site(documents)
        before = baseline["score"]

        lines = [
            "# Audit RGAA 4.1 — rapport avant / après",
            "",
            f"Site audité : {current['pages']} page(s) · {len(RULES)} règles · référence {ctx.as_of.isoformat()} · "
            "audit et corrections exécutés localement, hors ligne.",
            "",
            "## Résultat",
            "",
            "| | Avant | Après |",
            "| --- | --- | --- |",
            f"| Conformité (règles × pages) | {before['conform']}/{before['checks']} ({before['percent']} %) | "
            f"**{current['conform']}/{current['checks']} ({current['percent']} %)** |",
            f"| Violations | {before['violations']} | **{current['violations']}** |",
            f"| Règles en échec | {len(before['rules_ko'])} | **{len(current['rules_ko'])}** |",
            "",
            "## Détail par règle",
            "",
            "| Règle | Critère RGAA | Sévérité | Avant | Après |",
            "| --- | --- | --- | --- | --- |",
        ]
        for rule in RULES:
            state_before = "conforme" if rule.id in before["rules_ok"] else "non conforme"
            state_after = "conforme" if rule.id in current["rules_ok"] else "non conforme"
            lines.append(f"| {rule.label} (`{rule.id}`) | {rule.rgpa} | {rule.severity} | {state_before} | {state_after} |")

        lines += ["", f"## Corrections appliquées ({len(patches)})", ""]
        if patches:
            for index, patch in enumerate(patches, start=1):
                detail = f"{patch['op']}"
                if patch.get("name"):
                    detail += f" {patch['name']}"
                if patch.get("value"):
                    detail += f' = "{patch["value"]}"'
                lines.append(f"{index}. `{patch['page']}` · `{patch['selector']}` · {detail}")
        else:
            lines.append("- Aucune correction appliquée.")

        if findings:
            lines += ["", "## Violations restantes", ""]
            for finding in findings:
                lines.append(
                    f"- **{finding.rule}** ({finding.rgpa}, {finding.severity}) — `{finding.page}` `{finding.selector}` : {finding.message}"
                )
        else:
            lines += ["", "## Violations restantes", "", "Aucune : les 12 règles passent sur toutes les pages au moment de la génération."]

        lines += [
            "",
            "## Portée de ce rapport",
            "",
            "Les 12 règles sont vérifiées mécaniquement sur l'arbre HTML (balises, attributs, texte accessible, "
            "contraste calculé depuis les styles en ligne). Ce n'est pas un audit complet des 106 critères du RGAA : "
            "la pertinence éditoriale d'un texte alternatif, la qualité d'un intitulé de lien ou l'accessibilité "
            "d'un contenu dynamique restent des jugements humains.",
            "",
        ]
        path = ctx.sandbox.write(f"deliverables/{name}", "\n".join(lines) + "\n")
        return {
            "written": f"deliverables/{name}",
            "bytes": path.stat().st_size,
            "conform_before": before["percent"],
            "conform_after": current["percent"],
            "violations_after": current["violations"],
        }

    @reg.tool(
        "inspect_image",
        "Décrit réellement une image avec un modèle vision local (Qwen2.5-VL, LLaVA, moondream...). "
        "Retourne available=false si aucun VLM n'est chargé : il faut alors décrire depuis le contexte HTML.",
        required=("path",),
        optional={"question": ""},
    )
    def inspect_image(path: str, question: str = "") -> dict[str, Any]:
        target = ctx.sandbox.resolve(path)
        if not target.is_file():
            raise ToolError(f"image introuvable : {path} — images présentes : {', '.join(p.name for p in ctx.sandbox.root.glob('*.png')) or 'aucune'}")
        config = ctx.vision or {}
        try:
            result = describe_image(
                target,
                base_url=config.get("base_url"),
                model=config.get("model"),
                prompt=question,
                api_key=config.get("api_key"),
                timeout=int(config.get("timeout", 90)),
            )
        except (ValueError, OSError) as exc:
            raise ToolError(f"vision indisponible : {exc}") from exc
        return {"path": path, "bytes": target.stat().st_size, **result}

    @reg.tool(
        "contrast_propose",
        "Propose la teinte la plus proche qui atteint le seuil de contraste, en conservant la teinte d'origine. "
        "Renvoie la couleur, le ratio obtenu et le ratio d'origine.",
        required=("color", "background"),
        optional={"target": 4.5},
    )
    def contrast_propose(color: str, background: str, target: float = 4.5) -> dict[str, Any]:
        try:
            return propose_compliant(color, background, float(target))
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @reg.tool(
        "report_html",
        "Génère le rapport HTML autonome avant/après : diff coloré des corrections, critères RGAA validés, résumé exécutif.",
        optional={"name": "rapport-rgaa.html"},
    )
    def report_html(name: str = "rapport-rgaa.html") -> dict[str, Any]:
        baseline = _baseline(ctx)
        documents = _load(ctx)
        current = score(documents)
        patches = _read_json(ctx.sandbox.root / PATCH_LOG, [])
        findings = audit_site(documents)
        markup = render_report(
            baseline=baseline,
            current=current,
            patches=patches,
            findings=findings,
            pages=sorted(documents),
            as_of=ctx.as_of,
            mode=ctx.mode,
        )
        path = ctx.sandbox.write(f"deliverables/{name}", markup)
        return {
            "written": f"deliverables/{name}",
            "bytes": path.stat().st_size,
            "conform_before": baseline["score"]["percent"],
            "conform_after": current["percent"],
            "patches": len(patches),
            "violations_after": current["violations"],
        }

    return reg
