"""Sous-agents : un travailleur par page, un orchestrateur qui agrège.

Chaque page est confiée à un sous-agent indépendant : il reçoit sa page, ses
outils, son budget de correction, et il rend un résultat mesuré (avant, après,
corrections, durée). Les sous-agents travaillent en parallèle sur des copies
distinctes, donc sans conflit d'écriture ; l'orchestrateur recolle les pages,
recalcule le score global et produit les rapports.

Ce sont des sous-agents déterministes : même moteur que le mode CI, appliqué par
page. En mode live, la même interface peut leur donner un modèle, le découpage
par page reste identique.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import ci
from .audit import audit_page, audit_site, score
from .dom import parse

FAMILIES = {
    "img-alt": "media",
    "link-name": "media",
    "button-name": "media",
    "iframe-title": "media",
    "label": "formulaires",
    "headings": "structure",
    "list-structure": "structure",
    "duplicate-id": "structure",
    "lang": "langue",
    "title": "langue",
    "contrast": "contraste",
    "table-header": "tableaux",
}


def _role(document: Any, page: str) -> str:
    """Spécialité d'un sous-agent : la famille de règles la plus fréquente sur sa page."""
    counts: dict[str, int] = {}
    for finding in audit_page(page, document):
        family = FAMILIES.get(finding.rule, "divers")
        counts[family] = counts.get(family, 0) + 1
    if not counts:
        return "conformité"
    return max(counts.items(), key=lambda item: item[1])[0]


def run_team(
    site: Path,
    *,
    workers: int | None = None,
    write: bool = False,
    lang: str = "fr",
    vision: dict[str, Any] | None = None,
    base_url: str | None = None,
    agents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pages = ci.site_pages(Path(site))
    if not pages:
        raise FileNotFoundError(f"aucune page HTML trouvée dans {site}")

    originals = {name: path.read_text(encoding="utf-8") for name, path in pages.items()}
    baseline_docs = {name: parse(markup) for name, markup in originals.items()}
    baseline = score(baseline_docs)

    def work(item: tuple[str, str]) -> dict[str, Any]:
        name, markup = item
        started = time.perf_counter()
        document = parse(markup)
        role = _role(document, name)  # spécialité déduite de l'état initial, pas de l'état corrigé
        patches: list[dict[str, Any]] = []
        ci._fix_page(name, document, lang, patches)  # même moteur que le mode CI
        result = score({name: document})
        return {
            "agent": f"agent-{Path(name).stem}",
            "page": name,
            "role": role,
            "before": score({name: parse(markup)})["percent"],
            "after": result["percent"],
            "violations_after": result["violations"],
            "patches": len(patches),
            "review": sum(1 for patch in patches if patch.get("review")),
            "ms": round((time.perf_counter() - started) * 1000),
            "html": document.serialize(),
            "patch_details": patches,
        }

    def work_group(spec: dict[str, Any], selected: list[str]) -> dict[str, Any]:
        """Sous-agent personnalisé : il traite les pages qu'on lui confie, dans son rôle."""
        started = time.perf_counter()
        patches: list[dict[str, Any]] = []
        html: dict[str, str] = {}
        before_points = after_points = 0.0
        for name in selected:
            document = parse(originals[name])
            ci._fix_page(name, document, lang, patches)
            html[name] = document.serialize()
            before_points += score({name: parse(originals[name])})["percent"]
            after_points += score({name: document})["percent"]
        count = max(1, len(selected))
        return {
            "agent": str(spec.get("name") or "agent-libre")[:40],
            "page": ", ".join(selected) if selected else "aucune",
            "role": str(spec.get("role") or "libre")[:40],
            "before": round(before_points / count, 1),
            "after": round(after_points / count, 1),
            "violations_after": 0,
            "patches": len(patches),
            "review": sum(1 for patch in patches if patch.get("review")),
            "ms": round((time.perf_counter() - started) * 1000),
            "html": "",
            "patch_details": patches,
            "_html": html,
        }

    started = time.perf_counter()
    if agents:
        specs = []
        for spec in agents[:8]:
            wanted = [chunk.strip() for chunk in str(spec.get("pages") or "toutes").split(",") if chunk.strip()]
            selected = [name for name in originals if not wanted or "toutes" in wanted or name in wanted]
            specs.append((spec, selected))
        with ThreadPoolExecutor(max_workers=int(workers or min(4, len(specs) or 1))) as pool:
            results = list(pool.map(lambda pair: work_group(*pair), specs))
        merged: dict[str, Any] = {}
        for entry in results:
            merged.update(entry.pop("_html", {}))
        merged = {name: parse(markup) for name, markup in merged.items()}
    else:
        with ThreadPoolExecutor(max_workers=int(workers or min(4, len(pages)))) as pool:
            results = list(pool.map(work, sorted(originals.items())))
        merged = {entry["page"]: parse(entry["html"]) for entry in results}
    elapsed = round((time.perf_counter() - started) * 1000)
    patches = [patch for entry in results for patch in entry["patch_details"]]

    # Passe vision commune : les images ne sont pas découpées par page, un seul agent s'en charge.
    vision_report: dict[str, Any] = {"available": False, "images": 0, "findings": 0, "fixes": 0}
    if vision and vision.get("base_url") and vision.get("model"):
        from .vision_audit import apply_to_documents, audit_documents

        started = time.perf_counter()
        vision_report = audit_documents(merged, Path(site), vision, base_url=base_url)
        vision_patches = apply_to_documents(merged, vision_report.get("findings", []))
        patches.extend(vision_patches)
        results.append(
            {
                "agent": "agent-vision",
                "page": "toutes",
                "role": "vision",
                "before": baseline["percent"],
                "after": score(merged)["percent"],
                "violations_after": 0,
                "patches": len(vision_patches),
                "review": 0,
                "ms": round((time.perf_counter() - started) * 1000),
                "html": "",
                "patch_details": vision_patches,
            }
        )
        vision_report = {
            "available": vision_report["available"],
            "model": vision_report.get("model", ""),
            "images": len(vision_report.get("images", [])),
            "findings": len(vision_report.get("findings", [])),
            "fixes": len(vision_patches),
            "skipped": len(vision_report.get("skipped", [])),
            "details": vision_report.get("findings", []),
        }

    current = score(merged)
    findings = audit_site(merged)

    if write:
        for name, document in merged.items():
            if name in pages:
                pages[name].write_text(document.serialize(), encoding="utf-8")

    return {
        "site": str(Path(site).resolve()),
        "workers": len(results),
        "agents": [{key: value for key, value in entry.items() if key not in {"html", "patch_details"}} for entry in results],
        "baseline": baseline,
        "score": current,
        "patches": len(patches),
        "review": sum(1 for patch in patches if patch.get("review")),
        "findings": [
            {"rule": finding.rule, "page": finding.page, "selector": finding.selector, "message": finding.message}
            for finding in findings
        ],
        "ms": elapsed,
        "vision": vision_report,
        "documents": merged,
    }


def apply_report(team_result: dict[str, Any], sandbox: Path, name: str = "rapport-equipe.html") -> Path:
    """Rapport HTML de l'équipe : mêmes sections que le mode CI, plus le tableau des sous-agents."""
    from .report import render_report

    team = team_result
    patches = []
    for agent in team["agents"]:
        patches.append(
            {
                "page": agent["page"],
                "selector": agent["agent"],
                "op": f"sous-agent {agent['role']} · {agent['patches']} correction(s) en {agent['ms']} ms",
                "before": f"{agent['before']} % de conformité",
                "after": f"{agent['after']} % de conformité",
            }
        )
    markup = render_report(
        baseline={"score": team["baseline"]},
        current=team["score"],
        patches=patches,
        findings=[],
        pages=sorted(team["documents"]),
        as_of=__import__("datetime").date.today(),
        mode="équipe",
    )
    target = Path(sandbox) / "deliverables" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markup, encoding="utf-8")
    return target
