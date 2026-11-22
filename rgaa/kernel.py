"""RGAA Agent — noyau d'agent local (bibliothèque standard uniquement).

Quatre responsabilités, volontairement séparées du domaine métier :

* ``Registry``  : table d'outils + validation stricte des signatures ;
* ``Sandbox``   : répertoire d'exécution, toute sortie de chemin est refusée ;
* ``SkillsStore`` : procédures apprises, persistées **hors** du bac à sable du run ;
* ``run_campagne`` : boucle objectif → outil → observation → vérification, avec
  budget d'étapes, journal JSONL et artefacts.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
CAMPAGNE_DIR = ROOT / "campagnes"
# Les deux seuls répertoires d'écriture : surchargeables pour un conteneur ou des tests.
RUNS_DIR = Path(os.environ.get("RGAA_RUNS", ROOT / "runs"))
DATA_DIR = Path(os.environ.get("RGAA_DATA", ROOT / "data"))


class ToolError(Exception):
    """Erreur d'exécution d'un outil : rendue à l'agent comme observation."""


class SandboxError(ToolError):
    """Tentative de sortie du bac à sable."""


# --------------------------------------------------------------------------- #
# Registre d'outils
# --------------------------------------------------------------------------- #
@dataclass
class Tool:
    name: str
    doc: str
    required: tuple[str, ...]
    fn: Callable[..., Any]
    optional: dict[str, Any] = field(default_factory=dict)

    def signature(self) -> str:
        bits = list(self.required) + [f"{k}={v!r}" for k, v in self.optional.items()]
        return f"{self.name}({', '.join(bits)})"

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "signature": self.signature(), "doc": self.doc}


class Registry:
    """Table d'outils. Toute erreur d'appel devient une observation, jamais un crash."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def tool(
        self,
        name: str,
        doc: str,
        required: tuple[str, ...] = (),
        optional: dict[str, Any] | None = None,
    ):
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[name] = Tool(name, doc, tuple(required), fn, dict(optional or {}))
            return fn

        return deco

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def call(self, name: Any, args: Any) -> dict[str, Any]:
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return {
                "ok": False,
                "error": f"outil inconnu : {name!r}",
                "hint": "outils disponibles : " + ", ".join(self.names()),
            }
        if not isinstance(args, dict):
            return {"ok": False, "error": "args doit être un objet JSON", "signature": tool.signature()}
        missing = [p for p in tool.required if p not in args]
        extra = [k for k in args if k not in tool.required and k not in tool.optional]
        if missing:
            return {
                "ok": False,
                "error": "arguments manquants : " + ", ".join(missing),
                "signature": tool.signature(),
            }
        if extra:
            return {
                "ok": False,
                "error": "arguments inconnus : " + ", ".join(extra),
                "signature": tool.signature(),
            }
        call_args = {**tool.optional, **args}
        try:
            return {"ok": True, "result": tool.fn(**call_args)}
        except ToolError as exc:
            return {"ok": False, "error": str(exc), "signature": tool.signature()}
        except Exception as exc:  # noqa: BLE001 - l'erreur est une observation, pas un arrêt
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "signature": tool.signature(),
            }


# --------------------------------------------------------------------------- #
# Bac à sable
# --------------------------------------------------------------------------- #
class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, rel: str) -> Path:
        raw = str(rel).strip().replace("\\", "/")
        if not raw:
            raise SandboxError("chemin vide")
        if raw.startswith(("/", "~")) or re.match(r"^[a-zA-Z]:", raw):
            raise SandboxError(f"chemin absolu refusé : {rel}")
        target = (self.root / raw).resolve()
        if target != self.root and self.root not in target.parents:
            raise SandboxError(f"sortie du bac à sable refusée : {rel}")
        return target

    def write(self, rel: str, content: str) -> Path:
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def tree(self, skip: tuple[str, ...] = ("ledger.json",)) -> list[str]:
        out = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and p.name not in skip:
                out.append(str(p.relative_to(self.root)))
        return out


def normalize(text: str) -> str:
    """Minuscules sans accents : recherche tolérante sur du texte français."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


# --------------------------------------------------------------------------- #
# Procédures apprises (hors bac à sable : elles survivent aux runs)
# --------------------------------------------------------------------------- #
class SkillsStore:
    def __init__(self, base: Path) -> None:
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, content: str) -> dict[str, Any]:
        slug = re.sub(r"[^a-z0-9]+", "-", normalize(name)).strip("-") or "procedure"
        path = self.base / f"{slug}.md"
        body = content.strip()
        path.write_text(f"# {name.strip()}\n\n{body}\n", encoding="utf-8")
        return {"name": name, "slug": slug, "path": str(path.name), "chars": len(body)}

    def recall(self, topic: str, limit: int = 3) -> list[dict[str, Any]]:
        tokens = {t for t in re.split(r"\W+", normalize(topic)) if len(t) > 2}
        scored = []
        for path in sorted(self.base.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            haystack = normalize(text)
            score = sum(haystack.count(t) for t in tokens)
            if score:
                scored.append((score, path, text))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [
            {"name": _first_heading(text) or path.stem, "slug": path.stem, "content": text.strip()}
            for _, path, text in scored[:limit]
        ]

    def listing(self) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.base.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            rows.append(
                {
                    "name": _first_heading(text) or path.stem,
                    "slug": path.stem,
                    "chars": len(text),
                    "preview": " ".join(text.split())[:220],
                }
            )
        return rows


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


# --------------------------------------------------------------------------- #
# Journal
# --------------------------------------------------------------------------- #
class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# Contexte partagé par les outils
# --------------------------------------------------------------------------- #
@dataclass
class Ctx:
    sandbox: Sandbox
    as_of: dt.date
    skills: SkillsStore
    campagne: str
    registry: Registry | None = None
    mode: str = "replay"
    vision: dict[str, Any] | None = None

    @property
    def deliverables(self) -> Path:
        path = self.sandbox.root / "deliverables"
        path.mkdir(parents=True, exist_ok=True)
        return path


# --------------------------------------------------------------------------- #
# Chargement des campagnes
# --------------------------------------------------------------------------- #
def campagne_paths(slug: str) -> Path:
    path = CAMPAGNE_DIR / slug
    if not (path / "campagne.json").is_file():
        raise FileNotFoundError(f"campagne inconnu : {slug}")
    return path


def load_campagne(slug: str) -> dict[str, Any]:
    data = json.loads((campagne_paths(slug) / "campagne.json").read_text(encoding="utf-8"))
    data.setdefault("slug", slug)
    data.setdefault("budget", 14)
    data.setdefault("passes", [{"label": "passe unique", "cassette": "cassette.json"}])
    data["_dir"] = campagne_paths(slug)
    return data


def list_campagnes() -> list[dict[str, Any]]:
    out = []
    if not CAMPAGNE_DIR.is_dir():
        return out
    for path in sorted(CAMPAGNE_DIR.iterdir()):
        if (path / "campagne.json").is_file():
            try:
                scen = load_campagne(path.name)
            except (json.JSONDecodeError, OSError):
                continue
            fixtures = []
            fx_name = scen.get("fixtures") or path.name
            fx = ROOT / "fixtures" / fx_name
            if fx.is_dir():
                fixtures = sorted(p.name for p in fx.iterdir() if p.is_file())
            out.append(
                {
                    "slug": scen["slug"],
                    "title": scen.get("title", scen["slug"]),
                    "objective": scen.get("objective", ""),
                    "budget": scen["budget"],
                    "as_of": scen.get("as_of"),
                    "engine": scen.get("engine", "cassette"),
                    "learning": len(scen["passes"]) > 1,
                    "passes": [p.get("label", f"passe {i + 1}") for i, p in enumerate(scen["passes"])],
                    "fixtures": fixtures,
                }
            )
    return out


# --------------------------------------------------------------------------- #
# Boucle d'exécution
# --------------------------------------------------------------------------- #
def _execute_pass(
    ctx: Ctx,
    registry: Registry,
    planner: Any,
    journal: Journal,
    objective: str,
    budget: int,
    pass_label: str,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    errors = 0
    status = "budget"
    final = ""

    for index in range(1, budget + 1):
        step = planner.next_step(objective, steps)
        if not isinstance(step, dict):
            step = {"thought": "plan illisible", "tool": None, "args": {}}
        if "final" in step:
            final = str(step["final"])
            status = "done"
            journal.write(
                {"pass": pass_label, "step": index, "type": "final", "thought": step.get("thought", ""), "final": final}
            )
            break

        name, args = step.get("tool"), step.get("args") or {}
        observation = registry.call(name, args)
        if not observation.get("ok"):
            errors += 1
        record = {
            "pass": pass_label,
            "step": index,
            "type": "tool",
            "thought": str(step.get("thought", "")),
            "tool": name,
            "args": args,
            "ok": bool(observation.get("ok")),
            "observation": observation,
        }
        steps.append(record)
        journal.write(record)
    else:
        journal.write({"pass": pass_label, "type": "budget_exhausted", "budget": budget})

    return {
        "label": pass_label,
        "status": status,
        "steps": len(steps),
        "errors": errors,
        "final": final,
        "records": steps,
    }


def _collect_artifacts(sandbox: Sandbox) -> list[dict[str, Any]]:
    out = []
    for path in sorted(sandbox.root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(sandbox.root).as_posix()
        patched = (sandbox.root / "rgaa-patches.json").is_file()
        if rel.startswith(("deliverables/", "alerts/")) or rel == "rgaa-patches.json" or (patched and rel.endswith((".html", ".htm"))):
            out.append({"name": rel, "bytes": path.stat().st_size})
    return out


def run_campagne(
    slug: str,
    mode: str = "replay",
    live: dict[str, Any] | None = None,
    as_of: str | None = None,
    max_steps: int | None = None,
    runs_dir: Path | str = RUNS_DIR,
    vision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .planners import LivePlanner, ReplayPlanner
    from .tools import build_registry

    scen = load_campagne(slug)
    run_id = f"{slug}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    run_dir = Path(runs_dir) / run_id
    sandbox = Sandbox(run_dir / "sandbox")

    fixtures = ROOT / "fixtures" / (scen.get("fixtures") or slug)
    if fixtures.is_dir():
        shutil.copytree(fixtures, sandbox.root, dirs_exist_ok=True)

    reference = as_of or scen.get("as_of") or dt.date.today().isoformat()
    ctx = Ctx(
        sandbox=sandbox,
        as_of=dt.date.fromisoformat(reference),
        skills=SkillsStore(DATA_DIR / "skills" / slug),
        campagne=slug,
        mode=mode,
        vision=vision,
    )
    registry = Registry()
    build_registry(registry, ctx)
    ctx.registry = registry

    journal = Journal(run_dir / "journal.jsonl")
    budget = int(max_steps or scen["budget"])
    passes: list[dict[str, Any]] = []

    for entry in scen["passes"]:
        label = entry.get("label", "passe")
        if mode == "live":
            config = dict(live or {})
            planner = LivePlanner(
                base_url=config.get("base_url", "http://127.0.0.1:11434"),
                model=config.get("model", "qwen2.5-coder:7b"),
                api_key=config.get("api_key"),
                timeout=int(config.get("timeout", 180)),
            )
        else:
            cassette = json.loads((Path(scen["_dir"]) / entry["cassette"]).read_text(encoding="utf-8"))
            planner = ReplayPlanner(cassette.get("steps", cassette))
        passes.append(_execute_pass(ctx, registry, planner, journal, scen.get("objective", ""), budget, label))

    status = "done" if all(p["status"] == "done" for p in passes) else "budget"
    result = {
        "run_id": run_id,
        "campagne": slug,
        "title": scen.get("title", slug),
        "objective": scen.get("objective", ""),
        "mode": mode,
        "as_of": reference,
        "budget": budget,
        "status": status,
        "passes": passes,
        "steps": [record for p in passes for record in p["records"]],
        "errors": sum(p["errors"] for p in passes),
        "final": passes[-1]["final"] if passes else "",
        "artifacts": _collect_artifacts(sandbox),
        "skills": ctx.skills.listing(),
        "tools": registry.specs(),
        "run_dir": str(run_dir),
        "journal": str(journal.path),
    }
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def read_artifact(run_id: str, name: str, runs_dir: Path | str = RUNS_DIR) -> Path:
    run_dir = (Path(runs_dir) / run_id / "sandbox").resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(run_id)
    target = (run_dir / name).resolve()
    if run_dir not in target.parents:
        raise SandboxError(f"artefact hors du run : {name}")
    if not target.is_file():
        raise FileNotFoundError(name)
    return target
