"""Export d'un run : archive ZIP prête à envoyer ou à archiver.

Un run contient tout ce qu'un relecteur peut vouloir : pages corrigées, rapports,
journal des patchs, centre de calcul du score. L'export les emballe sans
réseau, avec un manifeste lisible.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

MANIFEST = "MANIFESTE.txt"


def build_zip(run_dir: Path) -> bytes:
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(run_dir)

    files = [path for path in sorted(run_dir.rglob("*")) if path.is_file() and ".git" not in path.parts]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(run_dir).as_posix())
        archive.writestr(
            MANIFEST,
            "\n".join(
                [
                    "Export RGAA Agent",
                    f"run : {run_dir.name}",
                    f"fichiers : {len(files)}",
                    "",
                    "Contenu :",
                    "- sandbox/ : pages corrigées, rapports, journal des patchs",
                    "- result.json : scores, étapes, artefacts",
                    "- journal.jsonl : une ligne par étape d'agent (si présent)",
                    "",
                    "Aucune ressource externe, aucune donnée envoyée.",
                ]
            )
            + "\n",
        )
    return buffer.getvalue()


def summary(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    result_path = run_dir / "result.json"
    payload = {}
    if result_path.is_file():
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    files = [path.relative_to(run_dir).as_posix() for path in sorted(run_dir.rglob("*")) if path.is_file()]
    return {
        "run": run_dir.name,
        "files": files,
        "campagne": payload.get("campagne") or payload.get("mode"),
        "status": payload.get("status"),
        "steps": len(payload.get("steps", [])) if isinstance(payload.get("steps"), list) else payload.get("steps"),
        "errors": payload.get("errors"),
    }
