"""Serveur HTTP local : UI de démonstration + API JSON. Bibliothèque standard.

Endpoints :
  GET  /                     interface
  GET  /healthz              sonde de vie (utilisée par la CI et Docker)
  GET  /api/campagnes        catalogue
  GET  /api/skills           procédures apprises (toutes survivantes aux runs)
  GET  /api/runs             runs récents
  GET  /api/runs/<id>        résultat complet d'un run
  GET  /api/artifact?run=&name=  artefact (markdown, json, html corrigé)
  POST /api/run              {campagne, mode, base_url, model, api_key}
  POST /api/probe            {base_url} -> modèles exposés
"""

from __future__ import annotations

import datetime as dt
import json
import mimetypes
import shutil
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import kernel
from . import campaigns
from .audit import RULES
from .ci import run_ci
from .export import build_zip
from .kernel import RUNS_DIR, ROOT, SkillsStore, DATA_DIR
from .planners import list_models
from .remote import RemoteError, fetch, save
from .team import apply_report, run_team
from .ui import INDEX_HTML

CHARSET_TYPES = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".html": "text/html",
    ".svg": "image/svg+xml",
}
_RUN_LOCK = threading.Lock()
_DEMO_LOCK = threading.Lock()
_DEMO_INFO: dict[str, Any] | None = None


def _demo_cached() -> dict[str, Any]:
    """La démo coûte un audit complet : on la prépare une fois, puis on la sert."""
    global _DEMO_INFO
    with _DEMO_LOCK:
        if _DEMO_INFO is None:
            from .demo import prepare

            _DEMO_INFO = prepare()
        return _DEMO_INFO


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _new_run(prefix: str) -> tuple[str, Path, Path]:
    run_id = f"{prefix}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    run_dir = Path(RUNS_DIR) / run_id
    sandbox = run_dir / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir, sandbox


def _artifacts(sandbox: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(Path(sandbox).rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(sandbox).as_posix()
        if rel.startswith(("deliverables/", "alerts/")) or rel.endswith(".html") or rel == "rgaa-patches.json":
            rows.append({"name": rel, "bytes": path.stat().st_size})
    return rows


def _auto_campaign(slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Campagne sans cassette : corrections déterministes, journal synthétique."""
    data = campaigns.load(slug)
    run_id, run_dir, sandbox = _new_run(slug)
    shutil.copytree(campaigns.site_path(slug), sandbox, dirs_exist_ok=True)
    vision = {
        "base_url": payload.get("vision_url") or None,
        "model": payload.get("vision_model") or None,
    }
    result = run_ci(
        sandbox,
        min_score=float(payload.get("min_score") or 100.0),
        write=True,
        report_path=sandbox / "deliverables" / "rapport-rgaa.html",
        vision=vision,
    )
    steps = []
    for index, patch in enumerate(result["patches"], start=1):
        steps.append(
            {
                "pass": "auto",
                "step": index,
                "tool": "patch_html",
                "args": {"page": patch["page"], "selector": patch["selector"]},
                "thought": patch["op"],
                "ok": True,
                "observation": {"ok": True, "result": {"changed": patch.get("changed", 1), "page": patch["page"]}},
            }
        )
    steps.append(
        {
            "pass": "auto",
            "step": len(steps) + 1,
            "tool": "audit_score",
            "args": {},
            "thought": "score recalculé après les corrections",
            "ok": True,
            "observation": {"ok": True, "result": {"score": result["score"], "baseline": result["baseline"]}},
        }
    )
    final = (
        f"{result['baseline']['percent']} % (note {result['baseline']['grade']['letter']}) → "
        f"{result['score']['percent']} % (note {result['score']['grade']['letter']}), "
        f"{len(result['patches'])} corrections, {len(result['review'])} texte(s) à relire."
    )
    payload_out = {
        "run_id": run_id,
        "scenario": slug,
        "campagne": slug,
        "title": data.get("title", slug),
        "objective": data.get("objective", ""),
        "mode": "auto",
        "as_of": data.get("as_of"),
        "budget": data.get("budget", 24),
        "status": "done",
        "passes": [{"label": "campagne automatique", "status": "done", "steps": len(steps), "errors": 0, "final": final}],
        "steps": steps,
        "errors": 0,
        "final": final,
        "vision": result.get("vision", {}),
        "artifacts": _artifacts(sandbox),
        "skills": [],
        "tools": [],
        "run_dir": str(run_dir),
    }
    (run_dir / "result.json").write_text(json.dumps(payload_out, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload_out


def _ollama_status() -> dict[str, Any]:
    installed = shutil.which("ollama") is not None
    running = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as response:
            running = response.status == 200
    except Exception:  # noqa: BLE001
        running = False
    return {
        "installed": installed,
        "running": running,
        "url": "http://127.0.0.1:11434",
        "embedded": __import__("os").environ.get("RGAA_EMBEDDED_OLLAMA", "0") == "1",
    }


def _guess_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    base = CHARSET_TYPES.get(suffix) or (mimetypes.guess_type(name)[0] or "application/octet-stream")
    # Un type texte sans charset fait deviner latin-1 au navigateur : « é » devient « Ã© ».
    if base.startswith("text/") or base in {"application/json", "image/svg+xml"}:
        return f"{base}; charset=utf-8"
    return base


class Handler(BaseHTTPRequestHandler):
    server_version = "RGAAGent/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # silence par défaut
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    # -- helpers ---------------------------------------------------------- #
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

    def _send_download(self, body: bytes, content_type: str, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -- routes ----------------------------------------------------------- #
    def _demo(self, path: str) -> None:
        """Le mode démo, monté sur le port de l'application : un seul port à ouvrir."""
        from .demo import DEMO_PAGE, _guess_type, annotations

        info = _demo_cached()
        relative = path[len("/demo") :].lstrip("/")
        if relative in {"", "index.html"}:
            pages = sorted(p.name for p in Path(info["before"]).glob("*.html"))
            wanted = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("page") or ["tarifs.html"])[0]
            current = wanted if wanted in pages else pages[0]
            tabs = "".join(
                f'<a href="/demo?page={name}" class="{"on" if name == current else ""}">{name.replace(".html", "")}</a>'
                for name in pages
            )
            markup = (
                DEMO_PAGE.replace("__TABS__", tabs).replace("__PAGE__", current).replace("__PREFIX__", "/demo").replace("__BEFORE__", str(info["baseline"]["percent"]))
                .replace("__AFTER__", str(info["score"]["percent"]))
                .replace("__PATCHES__", str(info["patches"]))
            )
            self._send(200, markup.encode("utf-8"), "text/html; charset=utf-8")
            return
        if relative == "api/patches":
            self._send_json({"patches": info.get("details", [])})
            return
        if relative == "api/score":
            payload = {
                "avant": info["baseline"],
                "apres": info["score"],
                "corrections": info["patches"],
                "a_relire": info["review"],
                "pages": sorted(p.name for p in Path(info["before"]).glob("*.html")),
            }
            self._send(200, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8")
            return
        for prefix, root in (("site/avant/", info["before"]), ("site/apres/", info["after"])):
            if relative.startswith(prefix):
                target = Path(root) / relative[len(prefix) :]
                if target.is_file() and target.suffix == ".html" and prefix == "site/apres/":
                    markup = target.read_text(encoding="utf-8")
                    tag = annotations(info.get("details", []), target.name)
                    if tag:
                        markup = markup.replace("</head>", tag + "</head>", 1) if "</head>" in markup else tag + markup
                    self._send(200, markup.encode("utf-8"), "text/html; charset=utf-8")
                elif target.is_file():
                    self._send(200, target.read_bytes(), _guess_type(target.name))
                else:
                    self._send(404, b"introuvable", "text/plain; charset=utf-8")
                return
        if relative in {"rapport.html", "rapport"}:
            report = Path(info["report"])
            self._send(200, report.read_bytes(), "text/html; charset=utf-8")
            return
        self._send(404, b"introuvable", "text/plain; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/demo" or path.startswith("/demo/"):
            self._demo(path)
        elif path == "/":
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/healthz":
            self._send_json(
                {
                    "ok": True,
                    "version": kernel.__dict__.get("__version__", "1.0.0"),
                    "build": __import__("os").environ.get("RGAA_BUILD", "dev"),
                }
            )
        elif path == "/demo/api/run":
            from .demo import run_now

            mode = str(payload.get("mode") or "none")
            vision = {}
            if mode != "none":
                default_url = "http://127.0.0.1:11434" if mode == "local" else None
                vision = {
                    "base_url": payload.get("vision_url") or default_url,
                    "model": payload.get("vision_model") or None,
                }
                if not (vision["base_url"] and vision["model"]):
                    self._send_json({"error": "URL et modèle requis pour ce mode"}, 400)
                    return
            try:
                self._send_json(run_now(vision))
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        elif path == "/api/campagnes":
            self._send_json({"campagnes": kernel.list_campagnes(), "skills": _all_skills()})
        elif path == "/api/skills":
            self._send_json({"skills": _all_skills()})
        elif path == "/api/rules":
            self._send_json(
                {
                    "rules": [
                        {"id": rule.id, "label": rule.label, "rgpa": rule.rgpa, "severity": rule.severity}
                        for rule in RULES
                    ]
                }
            )
        elif path == "/api/settings":
            env = __import__("os").environ
            self._send_json(
                {
                    "ollama_url": env.get("RGAA_OLLAMA_URL", "http://127.0.0.1:11434"),
                    "ollama_model": env.get("RGAA_OLLAMA_MODEL", ""),
                    "vision_url": env.get("RGAA_VISION_URL", ""),
                    "vision_model": env.get("RGAA_VISION_MODEL", ""),
                    "in_container": env.get("RGAA_IN_CONTAINER", "") == "1",
                }
            )
        elif path == "/api/ollama/status":
            self._send_json(_ollama_status())
        elif path == "/api/capabilities":
            from . import browser as browser_mod

            info = browser_mod.available()
            self._send_json(
                {
                    "chrome": {
                        "available": info["available"],
                        "binary": info["binary"],
                        "xvfb": shutil.which("xvfb-run") is not None,
                        "mode": info["mode"],
                    },
                    "ollama": _ollama_status(),
                    "python": __import__("sys").version.split()[0],
                    "build": __import__("os").environ.get("RGAA_BUILD", "dev"),
                    "campagnes": len(kernel.list_campagnes()),
                    "rules": len(RULES),
                    "hints": {
                        "chrome": "image construite avec --build-arg INSTALL_BROWSER=1",
                        "ollama": "image construite avec --build-arg INSTALL_OLLAMA=1, puis RGAA_EMBEDDED_OLLAMA=1",
                        "note": "les arguments de build ne sont pas des variables d'environnement",
                    },
                }
            )
        elif path == "/api/export":
            run_id = (query.get("run") or [""])[0]
            fmt = (query.get("format") or ["zip"])[0].lower()
            if "/" in run_id or ".." in run_id or not run_id:
                self._send(400, b"run invalide", "text/plain; charset=utf-8")
                return
            run_dir = Path(RUNS_DIR) / run_id
            if not run_dir.is_dir():
                self._send(404, b"run inconnu", "text/plain; charset=utf-8")
                return
            sandbox = run_dir / "sandbox"
            try:
                if fmt == "zip":
                    self._send_download(build_zip(run_dir), "application/zip", f"{run_id}.zip")
                elif fmt == "json":
                    result_path = run_dir / "result.json"
                    body = result_path.read_bytes() if result_path.is_file() else _json_bytes({"run": run_id})
                    self._send_download(body, "application/json; charset=utf-8", f"{run_id}.json")
                elif fmt in {"html", "md"}:
                    candidates = sorted((sandbox / "deliverables").glob(f"*.{fmt}")) if (sandbox / "deliverables").is_dir() else []
                    if not candidates:
                        self._send(404, b"aucun rapport", "text/plain; charset=utf-8")
                        return
                    self._send_download(candidates[0].read_bytes(), _guess_type(candidates[0].name), candidates[0].name)
                else:
                    self._send(400, b"format inconnu", "text/plain; charset=utf-8")
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        elif path == "/api/runs":
            self._send_json({"runs": _recent_runs()})
        elif path.startswith("/api/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            result = Path(RUNS_DIR) / run_id / "result.json"
            if not result.is_file():
                self._send_json({"error": "run inconnu"}, 404)
            else:
                self._send_json(json.loads(result.read_text(encoding="utf-8")))
        elif path == "/api/artifact":
            run_id = (query.get("run") or [""])[0]
            name = (query.get("name") or [""])[0]
            try:
                target = kernel.read_artifact(run_id, name)
            except FileNotFoundError:
                self._send(404, b"artifact not found", "text/plain; charset=utf-8")
            except kernel.SandboxError as exc:
                self._send(403, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            else:
                self._send(200, target.read_bytes(), _guess_type(name))
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        payload = self._body()

        if path == "/api/run":
            slug = str(payload.get("campagne") or payload.get("slug") or "")
            mode = "live" if payload.get("mode") == "live" else "replay"
            live = {
                "base_url": payload.get("base_url") or "http://127.0.0.1:11434",
                "model": payload.get("model") or "qwen2.5-coder:7b",
                "api_key": payload.get("api_key") or None,
                "timeout": int(payload.get("timeout") or 180),
            }
            vision = {
                "base_url": payload.get("vision_url") or None,
                "model": payload.get("vision_model") or None,
            }
            if not slug:
                self._send_json({"error": "campagne requis"}, 400)
                return
            try:
                with _RUN_LOCK:
                    try:
                        campaign = campaigns.load(slug)
                    except campaigns.CampaignError:
                        campaign = None
                    if campaign and campaign.get("engine") == "auto":
                        result = _auto_campaign(slug, payload)
                    else:
                        result = kernel.run_campagne(
                            slug,
                            mode=mode,
                            live=live if mode == "live" else None,
                            as_of=payload.get("as_of") or None,
                            vision=vision,
                        )
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, 404)
                return
            except Exception as exc:  # noqa: BLE001 - l'UI doit afficher l'erreur, pas mourir
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            self._send_json(result)
        elif path == "/api/probe":
            try:
                self._send_json(list_models(str(payload.get("base_url") or "http://127.0.0.1:11434")))
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}", "hint": "vérifier l'hôte, le port et le suffixe /v1"}, 502)
        elif path == "/api/ci":
            workdir = Path(tempfile.mkdtemp(prefix="rgaa-ui-ci-"))
            site = workdir / "site"
            shutil.copytree(ROOT / "fixtures" / "site", site)
            try:
                result = run_ci(
                    site,
                    min_score=float(payload.get("min_score") or 100.0),
                    vision={
                        "base_url": payload.get("vision_url") or None,
                        "model": payload.get("vision_model") or None,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            self._send_json(
                {
                    "baseline": result["baseline"],
                    "score": result["score"],
                    "patches": len(result["patches"]),
                    "review": len(result["review"]),
                    "diff_lines": result["diff"].count("\n"),
                    "exit_code": result["exit_code"],
                    "passed": result["passed"],
                    "findings": result["findings"],
                    "vision": result.get("vision", {}),
                }
            )
        elif path == "/api/team":
            vision = {
                "base_url": payload.get("vision_url") or None,
                "model": payload.get("vision_model") or None,
            }
            try:
                run_id, run_dir, sandbox = _new_run("team")
                shutil.copytree(ROOT / "fixtures" / "site", sandbox, dirs_exist_ok=True)
                team = run_team(
                    sandbox,
                    workers=int(payload.get("workers") or 4),
                    write=True,
                    vision=vision,
                    agents=payload.get("agents") or None,
                )
                apply_report(team, sandbox)
                result = {
                    "run_id": run_id,
                    "campagne": "team",
                    "mode": "équipe",
                    "status": "done",
                    "steps": team["patches"],
                    "errors": 0,
                    "baseline": team["baseline"],
                    "score": team["score"],
                    "agents": team["agents"],
                    "patches": team["patches"],
                    "ms": team["ms"],
                    "vision": team.get("vision", {}),
                    "artifacts": _artifacts(sandbox),
                }
                (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                self._send_json({**result, "review": team["review"]})
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        elif path == "/api/scan":
            url = str(payload.get("url") or "").strip()
            try:
                page = fetch(url, allow_private=bool(payload.get("allow_private")))
            except RemoteError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            run_id, run_dir, sandbox = _new_run("scan")
            save(page, sandbox)
            report = sandbox / "deliverables" / "rapport-rgaa.html"
            vision = {
                "base_url": payload.get("vision_url") or None,
                "model": payload.get("vision_model") or None,
            }
            try:
                scan = run_ci(
                    sandbox,
                    min_score=float(payload.get("min_score") or 100.0),
                    write=True,
                    report_path=report,
                    vision=vision,
                    base_url=url,
                )
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                return
            browser_result: dict[str, Any] = {"available": False}
            if payload.get("browser"):
                try:
                    from . import browser as browser_mod
                    from . import browser_audit

                    rendered = browser_mod.render(
                        url=url, mode=payload.get("browser_mode") or None, budget_ms=4000, timeout=150.0
                    )
                    (sandbox / "deliverables").mkdir(parents=True, exist_ok=True)
                    (sandbox / "deliverables" / f"rendu-{page['name']}").write_text(
                        browser_mod.strip_report(rendered.html), encoding="utf-8"
                    )
                    browser_result = browser_audit.analyse(rendered.report, page["name"])
                    browser_result["ms"] = rendered.ms
                    browser_result["mode"] = rendered.mode
                    (sandbox / "deliverables" / "rendu-navigateur.json").write_text(
                        json.dumps(browser_result, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except Exception as exc:  # noqa: BLE001 - un navigateur absent ne casse pas le scan
                    browser_result = {"available": False, "error": f"{type(exc).__name__}: {exc}", "findings": []}
            result = {
                "run_id": run_id,
                "campagne": "scan",
                "mode": "url",
                "url": url,
                "page": page["name"],
                "bytes": page["bytes"],
                "status": "done",
                "steps": len(scan["patches"]),
                "errors": 0,
                "baseline": scan["baseline"],
                "score": scan["score"],
                "patches": len(scan["patches"]),
                "review": len(scan["review"]),
                "diff_lines": scan["diff"].count("\n"),
                "findings": scan["findings"],
                "vision": scan.get("vision", {}),
                "browser": browser_result,
                "artifacts": _artifacts(sandbox),
            }
            (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json(result)
        elif path == "/demo/api/run":
            from .demo import run_now

            mode = str(payload.get("mode") or "none")
            vision = {}
            if mode != "none":
                default_url = "http://127.0.0.1:11434" if mode == "local" else None
                vision = {
                    "base_url": payload.get("vision_url") or default_url,
                    "model": payload.get("vision_model") or None,
                }
                if not (vision["base_url"] and vision["model"]):
                    self._send_json({"error": "URL et modèle requis pour ce mode"}, 400)
                    return
            try:
                self._send_json(run_now(vision))
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        elif path == "/api/campagnes":
            try:
                payload_campagne = campaigns.create(
                    str(payload.get("title") or ""),
                    str(payload.get("objective") or ""),
                    budget=int(payload.get("budget") or 24),
                    pages=str(payload.get("pages") or "site"),
                )
            except campaigns.CampaignError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"campagne": payload_campagne, "campagnes": kernel.list_campagnes()}, 201)
        elif path == "/api/ollama/start":
            status = _ollama_status()
            if not status["installed"]:
                self._send_json({"error": "binaire ollama absent de cette image", **status}, 400)
                return
            if not status["running"]:
                try:
                    subprocess.Popen(  # noqa: S603 - binaire fixe, servi localement
                        ["ollama", "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    threading.Event().wait(2.5)
                except OSError as exc:
                    self._send_json({"error": str(exc), **status}, 500)
                    return
            self._send_json(_ollama_status())
        elif path == "/api/ollama/pull":
            model = str(payload.get("model") or "").strip()
            if not model:
                self._send_json({"error": "modèle requis"}, 400)
                return
            try:
                request = urllib.request.Request(
                    "http://127.0.0.1:11434/api/pull",
                    data=json.dumps({"model": model, "stream": False}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=900) as response:  # noqa: S310
                    body = json.loads(response.read().decode("utf-8"))
                self._send_json({"model": model, "status": body.get("status", "ok"), **_ollama_status()})
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 502)
        else:
            self._send_json({"error": "unknown endpoint"}, 404)

    # -- campagnes : modification et suppression ------------------------------- #
    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        payload = self._body()
        if parsed.path.startswith("/api/campagnes/"):
            slug = parsed.path.rsplit("/", 1)[-1]
            try:
                data = campaigns.update(slug, **payload)
            except campaigns.CampaignError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"campagne": data, "campagnes": kernel.list_campagnes()})
        else:
            self._send_json({"error": "unknown endpoint"}, 404)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/campagnes/"):
            slug = parsed.path.rsplit("/", 1)[-1]
            try:
                campaigns.delete(slug)
            except campaigns.CampaignError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self._send_json({"deleted": slug, "campagnes": kernel.list_campagnes()})
        else:
            self._send_json({"error": "unknown endpoint"}, 404)


def _all_skills() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = Path(DATA_DIR) / "skills"
    if not root.is_dir():
        return rows
    for campagne_dir in sorted(root.iterdir()):
        if campagne_dir.is_dir():
            for entry in SkillsStore(campagne_dir).listing():
                rows.append({"campagne": campagne_dir.name, **entry})
    return rows


def _recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    root = Path(RUNS_DIR)
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.iterdir(), reverse=True):
        result = path / "result.json"
        if not result.is_file():
            continue
        try:
            data = json.loads(result.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rows.append(
            {
                "run_id": data.get("run_id"),
                "campagne": data.get("campagne"),
                "mode": data.get("mode"),
                "status": data.get("status"),
                "steps": sum(p.get("steps", 0) for p in data.get("passes", [])),
                "errors": data.get("errors", 0),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def make_server(host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.verbose = False  # type: ignore[attr-defined]
    return httpd


def serve(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = False) -> int:
    httpd = make_server(host, port)
    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}/"
    print(f"RGAA Agent — interface sur {url}")
    print("Ctrl+C pour arrêter.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\narrêt.")
    finally:
        httpd.server_close()
    return 0
