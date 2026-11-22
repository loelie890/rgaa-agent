"""Publier un run : journal, transcription lisible, méta mesurée.

Un run qui n'est pas publié avec ses durées ne prouve rien. Ce module écrit trois
fichiers dans un dossier daté, avec ce qui a été mesuré, pas ce qu'on espère :
journal.jsonl brut, transcript.md lisible par un relecteur, meta.json pour la
machine. Les durées viennent d'un chronomètre, jamais d'une estimation.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any


def _transcript(result: dict[str, Any], meta: dict[str, Any]) -> str:
    lines = [
        f"# {meta['titre']}",
        "",
        f"- campagne : `{meta['campagne']}`",
        f"- objectif : {meta['objectif']}",
        f"- mode : {meta['mode']}",
        f"- modèle : {meta['modele'] or 'aucun'}",
        f"- modèle vision : {meta['modele_vision'] or 'aucun'}",
        f"- date : {meta['date']}",
        f"- durée mesurée : {meta['duree_s']} s pour {meta['etapes']} étapes",
        f"- erreurs : {meta['erreurs']}",
        "",
    ]
    for index, entry in enumerate(result.get("passes", []), start=1):
        if len(result.get("passes", [])) > 1:
            lines.append(f"## Passe {index} : {entry.get('label', '')}")
            lines.append("")
        for record in entry.get("records", []):
            mark = "ok" if record.get("ok") else "erreur"
            args = json.dumps(record.get("args", {}), ensure_ascii=False)
            lines.append(f"{record.get('step')}. **{record.get('tool')}** ({mark}) `{args}`")
            thought = (record.get("thought") or "").strip()
            if thought:
                lines.append(f"   > {thought}")
            observation = record.get("observation") or {}
            if not observation.get("ok"):
                lines.append(f"   resultat : {str(observation.get('error'))[:300]}")
            lines.append("")
        conclusion = (entry.get("final") or "").strip()
        if conclusion:
            lines.append(f"**Conclusion** : {conclusion[:1200]}")
            lines.append("")
    if result.get("artifacts"):
        lines.append("## Artefacts")
        lines.append("")
        for artifact in result["artifacts"]:
            lines.append(f"- `{artifact.get('name')}` ({artifact.get('bytes')} octets)")
        lines.append("")
    return "\n".join(lines)


def publish(
    result: dict[str, Any],
    run_dir: str | Path,
    target: str | Path,
    *,
    duration_s: float,
    model: str | None = None,
    vision_model: str | None = None,
    copy_artifacts: bool = True,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    out = Path(target)
    out.mkdir(parents=True, exist_ok=True)

    journal = run_path / "journal.jsonl"
    if journal.is_file():
        shutil.copy2(journal, out / "journal.jsonl")

    date = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    steps = sum(entry.get("steps", 0) for entry in result.get("passes", []))
    meta = {
        "titre": result.get("title", result.get("campagne", "run")),
        "campagne": result.get("campagne"),
        "objectif": result.get("objective"),
        "mode": result.get("mode", "replay"),
        "modele": model,
        "modele_vision": vision_model,
        "date": date,
        "duree_s": round(float(duration_s), 3),
        "etapes": steps,
        "erreurs": result.get("errors", 0),
        "budget": result.get("budget"),
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "par_etape_s": round(float(duration_s) / steps, 3) if steps else None,
        "artefacts": [item.get("name") for item in result.get("artifacts", [])],
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "transcript.md").write_text(_transcript(result, meta), encoding="utf-8")

    if copy_artifacts:
        source = run_path / "sandbox"
        if source.is_dir():
            destination = out / "artefacts"
            destination.mkdir(exist_ok=True)
            for item in result.get("artifacts", []):
                path = source / str(item.get("name"))
                if path.is_file():
                    target_file = destination / path.name
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target_file)
    return meta
