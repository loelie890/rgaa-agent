"""Mode démo : le site avant et après côte à côte, plus le rapport.

Un seul point d'entrée pour un juré qui veut voir, pas lire :

* ``/`` : démo visuelle, deux cadres côte à côte, score avant et après ;
* ``/site/avant/…`` et ``/site/apres/…`` : le site de démonstration servi tel
  quel dans les deux états, images comprises ;
* ``/rapport.html`` : le rapport HTML autonome produit par le moteur ;
* ``/api/score`` : les chiffres, en JSON, pour vérifier sans lire la page ;
* ``/healthz`` : sonde de vie.

Le site « après » n'est pas une maquette : il est obtenu en appliquant vraiment
les corrections mécaniques du mode CI sur une copie, puis en recalculant le
score. Aucun modèle n'est appelé.
"""

from __future__ import annotations

import json
import mimetypes
import shutil
import tempfile
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .audit import audit_site, score
from .ci import run_ci
from .dom import parse
from .kernel import ROOT

FIXTURES = ROOT / "fixtures" / "site"
DEFAULT_PORT = 8090

DEMO_PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Démo RGAA Agent, site avant et après corrections</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #fffaf7; color: #2b2430;
         font: 15px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
  header { padding: 20px 26px 14px; border-bottom: 1px solid #f0dfe7; display: flex; flex-wrap: wrap;
           gap: 14px; align-items: baseline; }
  h1 { margin: 0; font-size: 21px; }
  h1 span { color: #b03060; }
  header p { margin: 0; color: #6d5f6b; font-size: 13px; }
  .scores { margin-left: auto; display: flex; gap: 10px; flex-wrap: wrap; }
  .chip { border: 1px solid #f0dfe7; border-radius: 999px; padding: 4px 12px; font-size: 13px; color: #6d5f6b; }
  .chip b { color: #2b2430; }
  .chip.good { border-color: #cfe7d9; color: #1f6f4a; }
  main { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 18px 26px 40px; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  section { border: 1px solid #f0dfe7; border-radius: 12px; overflow: hidden; background: #ffffff; }
  section h2 { margin: 0; padding: 10px 14px; font-size: 13px; letter-spacing: .1em; text-transform: uppercase;
               color: #6d5f6b; border-bottom: 1px solid #f0dfe7; display: flex; justify-content: space-between; }
  section h2 a { color: #b03060; text-decoration: none; font-size: 12px; text-transform: none; letter-spacing: 0; }
  iframe { width: 100%; height: 620px; border: 0; background: #ffffff; display: block; }
  .run { background: #fff; border: 1px solid #f0dfe7; border-radius: 14px; padding: 18px 20px; margin-top: 18px; }
  .run h2 { margin: 0 0 6px; font-size: 15px; }
  .run p { margin: 0 0 12px; font-size: 13px; color: #6d5f6b; }
  .row { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
  .row label { font-size: 13px; color: #6d5f6b; min-width: 130px; }
  .row input, .row select { font: inherit; font-size: 13px; padding: 7px 10px; border: 1px solid #f0dfe7; border-radius: 9px; min-width: 260px; background: #fffaf7; }
  .run button { font: inherit; font-size: 13px; padding: 8px 16px; border-radius: 9px; border: 1px solid #b03060; background: #b03060; color: #fff; font-weight: 600; cursor: pointer; }
  .run button:disabled { opacity: .6; cursor: progress; }
  .out { font-size: 13px; color: #6d5f6b; }
  .pages { display: flex; gap: 8px; justify-content: center; margin: 18px 0 6px; flex-wrap: wrap; }
  .pages a { font-size: 13px; text-decoration: none; color: #6d5f6b; border: 1px solid #f0dfe7; background: #fff; border-radius: 999px; padding: 5px 14px; }
  .pages a.on { background: #b03060; border-color: #b03060; color: #fff; font-weight: 600; }
  .changes { background: #fff; border: 1px solid #f0dfe7; border-radius: 14px; padding: 16px 20px; margin-top: 14px; font-size: 13px; color: #4a3e47; }
  .changes h2 { margin: 0 0 8px; font-size: 14px; }
  .changes li { margin-bottom: 4px; }
  .changes code { color: #b03060; }
  footer { padding: 0 26px 28px; color: #6d5f6b; font-size: 12.5px; }
  footer a { color: #b03060; }
</style>
</head>
<body>
<header>
  <h1>RGAA <span>Agent</span></h1>
  <p>même site, mêmes fichiers, deux états : avant et après les corrections de l'agent</p>
  <div class="scores">
    <span class="chip">avant <b>__BEFORE__ %</b></span>
    <span class="chip good">après <b>__AFTER__ %</b></span>
    <span class="chip">__PATCHES__ corrections</span>
  </div>
</header>
<nav class="pages">__TABS__</nav>
<main>
  <section>
    <h2>Avant <a href="__PREFIX__/site/avant/__PAGE__">ouvrir en plein écran</a></h2>
    <iframe src="__PREFIX__/site/avant/__PAGE__" title="Site de démonstration avant corrections, avec silhouette d'accessibilité"></iframe>
  </section>
  <section>
    <h2>Après <a href="__PREFIX__/site/apres/__PAGE__">ouvrir en plein écran</a></h2>
    <iframe src="__PREFIX__/site/apres/__PAGE__" title="Site de démonstration après corrections de l'agent"></iframe>
  </section>
</main>
<section class="run">
  <h2>Relancer l'audit, ici et maintenant</h2>
  <p>Deux façons de regarder : les chiffres déjà calculés ci-dessus, ou une exécution
  réelle déclenchée maintenant. Le second mode prend quatre dixièmes de seconde sans
  modèle, et une à deux minutes par image avec un modèle vision local.</p>
  <div class="row">
    <label for="runMode">Moteur</label>
    <select id="runMode">
      <option value="none">Sans modèle, corrections déterministes (0,4 s)</option>
      <option value="remote">Endpoint distant : Ollama, LM Studio, vLLM</option>
      <option value="local">Ollama du conteneur, si l'image le contient</option>
    </select>
  </div>
  <div class="row" id="runUrlRow" hidden>
    <label for="runUrl">Serveur Ollama</label>
    <input id="runUrl" value="http://192.168.1.10:11434" spellcheck="false">
  </div>
  <div class="row" id="runModelRow" hidden>
    <label for="runModel">Modèle vision</label>
    <input id="runModel" value="moondream" spellcheck="false">
  </div>
  <section class="changes">
    <h2>Ce qui change sur cette page</h2>
    <ul class="clean" id="changesList"><li class="muted">chargement…</li></ul>
  </section>
  <div class="row">
    <button id="runBtn" type="button">Lancer maintenant</button>
    <span id="runOut" class="out">aucune exécution pour l'instant</span>
  </div>
</section>
<footer>
  Le site de droite est produit en appliquant réellement les corrections sur une copie, puis en recalculant le score.
  Aucun modèle, aucun réseau. <a href="__PREFIX__/rapport.html">Voir le rapport avant/après</a>, chiffres bruts sur <a href="__PREFIX__/api/score">/api/score</a>.
</footer>
<script>
(() => {
  const page = "__PAGE__";
  fetch("__PREFIX__/api/patches").then((r) => r.json()).then((data) => {
    const items = (data.patches || []).filter((p) => p.page === page);
    const list = document.getElementById("changesList");
    if (!items.length) { list.innerHTML = '<li class="muted">aucune correction sur cette page</li>'; return; }
    list.innerHTML = items.map((p) => `<li>${p.review ? "à relire · " : ""}<code>${p.selector || ""}</code> ${p.op || ""}</li>`).join("");
  }).catch(() => {});

  const mode = document.getElementById("runMode");
  const urlRow = document.getElementById("runUrlRow");
  const modelRow = document.getElementById("runModelRow");
  const out = document.getElementById("runOut");
  const btn = document.getElementById("runBtn");
  mode.addEventListener("change", () => {
    const value = mode.value;
    urlRow.hidden = value === "none";
    modelRow.hidden = value === "none";
  });
  btn.addEventListener("click", async () => {
    const body = { mode: mode.value };
    if (mode.value === "local") body.vision_url = "http://127.0.0.1:11434";
    if (mode.value === "remote") body.vision_url = document.getElementById("runUrl").value.trim();
    if (mode.value !== "none") body.vision_model = document.getElementById("runModel").value.trim();
    btn.disabled = true;
    out.textContent = "exécution en cours…";
    const started = performance.now();
    try {
      const response = await fetch("__PREFIX__/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await response.json();
      const ms = Math.round(performance.now() - started);
      if (data.error) { out.textContent = data.error; return; }
      const vision = data.vision && data.vision.available
        ? ` · vision ${data.vision.images} image(s), ${data.vision.fixes} alternative(s)`
        : "";
      out.textContent = `${data.before.percent} % → ${data.after.percent} % · ${data.patches} correction(s)${vision} · ${ms} ms mesurées`;
      document.querySelectorAll(".scores .chip b")[0].textContent = data.before.percent + " %";
      document.querySelectorAll(".scores .chip b")[1].textContent = data.after.percent + " %";
      document.querySelector(".scores .chip:last-child").textContent = data.patches + " corrections";
      document.querySelectorAll("main iframe")[1].src = "__PREFIX__/site/apres/__PAGE__?t=" + Date.now();
    } catch (error) {
      out.textContent = "échec : " + error;
    } finally {
      btn.disabled = false;
    }
  });
})();
</script>
</body>
</html>
"""

CHARSET_TYPES = {".html": "text/html", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json", ".md": "text/markdown"}


def prepare(workspace: Path | None = None) -> dict[str, Any]:
    """Construit les deux états du site et le rapport, hors ligne."""
    workspace = Path(workspace or tempfile.mkdtemp(prefix="rgaa-demo-"))
    before = workspace / "avant"
    after = workspace / "apres"
    for target in (before, after):
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(FIXTURES, target)

    report = workspace / "rapport.html"
    result = run_ci(after, min_score=100, write=True, report_path=report)

    baseline = score({name: parse(path.read_text(encoding="utf-8")) for name, path in _pages(before).items()})
    current = score({name: parse(path.read_text(encoding="utf-8")) for name, path in _pages(after).items()})

    return {
        "workspace": str(workspace),
        "before": str(before),
        "after": str(after),
        "report": str(report),
        "baseline": baseline,
        "score": current,
        "patches": len(result["patches"]),
        "details": [
            {
                "page": item.get("page"),
                "selector": item.get("selector"),
                "op": item.get("op"),
                "review": bool(item.get("review")),
            }
            for item in result["patches"]
        ],
        "review": len(result["review"]),
        "passed": result["passed"],
    }


def run_now(vision: dict[str, Any] | None = None) -> dict[str, Any]:
    """Exécute l'audit maintenant, sur une copie neuve, avec ou sans modèle."""
    import time

    started = time.perf_counter()
    workspace = Path(tempfile.mkdtemp(prefix="rgaa-demo-run-"))
    site = workspace / "site"
    shutil.copytree(FIXTURES, site)
    result = run_ci(
        site,
        min_score=100,
        write=True,
        report_path=workspace / "rapport.html",
        vision=vision or {},
    )
    return {
        "before": result["baseline"],
        "after": result["score"],
        "patches": len(result["patches"]),
        "details": [
            {
                "page": item.get("page"),
                "selector": item.get("selector"),
                "op": item.get("op"),
                "review": bool(item.get("review")),
            }
            for item in result["patches"]
        ],
        "review": len(result["review"]),
        "vision": result.get("vision", {}),
        "ms": round((time.perf_counter() - started) * 1000),
    }


def annotations(patches: list[dict[str, Any]], page: str) -> str:
    """Encadre dans la page corrigée les éléments que l'agent a modifiés."""
    selectors = [p["selector"] for p in patches if p.get("page") == page and p.get("selector")]
    if not selectors:
        return ""
    rules = "\n".join(
        f"{sel}{{outline:2px dashed #b03060 !important;outline-offset:3px}}"
        for sel in selectors[:40]
    )
    return f'<style id="rgaa-annotations">{rules}</style>'


def _pages(root: Path) -> dict[str, Path]:
    return {path.name: path for path in sorted(Path(root).glob("*.html"))}


def _guess_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    base = CHARSET_TYPES.get(suffix) or (mimetypes.guess_type(name)[0] or "application/octet-stream")
    if base.startswith("text/") or base in {"application/json", "image/svg+xml"}:
        return f"{base}; charset=utf-8"
    return base


class Handler(BaseHTTPRequestHandler):
    server_version = "RGAAAgentDemo/1.0"

    def log_message(self, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, root: Path, relative: str) -> None:
        target = (root / relative).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            self._send(403, b"chemin refuse", "text/plain; charset=utf-8")
            return
        if not target.is_file():
            self._send(404, b"introuvable", "text/plain; charset=utf-8")
            return
        self._send(200, target.read_bytes(), _guess_type(target.name))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {"/api/run", "/demo/api/run"}:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            payload = {}
        mode = str(payload.get("mode") or "none")
        vision = {}
        if mode != "none":
            default_url = "http://127.0.0.1:11434" if mode == "local" else None
            vision = {
                "base_url": payload.get("vision_url") or default_url,
                "model": payload.get("vision_model") or None,
            }
            if not (vision["base_url"] and vision["model"]):
                self._send(400, json.dumps({"error": "URL et modèle requis pour ce mode"}).encode(), "application/json; charset=utf-8")
                return
        try:
            result = run_now(vision)
        except Exception as exc:  # noqa: BLE001
            self._send(500, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json; charset=utf-8")
            return
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        info: dict[str, Any] = self.server.info  # type: ignore[attr-defined]

        if path in {"/", ""}:
            pages = sorted(p.name for p in Path(info["before"]).glob("*.html"))
            wanted = (urllib.parse.parse_qs(parsed.query).get("page") or ["tarifs.html"])[0]
            current = wanted if wanted in pages else pages[0]
            tabs = "".join(
                f'<a href="?page={name}" class="{"on" if name == current else ""}">{name.replace(".html", "")}</a>'
                for name in pages
            )
            markup = (
                DEMO_PAGE.replace("__PREFIX__", "").replace("__TABS__", tabs).replace("__PAGE__", current).replace("__BEFORE__", str(info["baseline"]["percent"]))
                .replace("__AFTER__", str(info["score"]["percent"]))
                .replace("__PATCHES__", str(info["patches"]))
            )
            self._send(200, markup.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/healthz":
            self._send(200, b'{"ok": true}', "application/json; charset=utf-8")
        elif path == "/api/patches":
            payload = {"patches": info.get("details", [])}
            self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        elif path == "/api/score":
            payload = {
                "avant": info["baseline"],
                "apres": info["score"],
                "corrections": info["patches"],
                "a_relire": info["review"],
                "pages": sorted(_pages(Path(info["before"]))),
            }
            self._send(200, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8")
        elif path.startswith("/site/avant/"):
            self._static(Path(info["before"]), path[len("/site/avant/") :])
        elif path.startswith("/site/apres/"):
            relative = path[len("/site/apres/") :]
            target = Path(info["after"]) / relative
            if target.is_file() and target.suffix == ".html":
                markup = target.read_text(encoding="utf-8")
                tag = annotations(info.get("details", []), target.name)
                if tag:
                    markup = markup.replace("</head>", tag + "</head>", 1) if "</head>" in markup else tag + markup
                self._send(200, markup.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._static(Path(info["after"]), relative)
        elif path in {"/rapport.html", "/rapport"}:
            self._static(Path(info["report"]).parent, Path(info["report"]).name)
        else:
            self._send(404, b"introuvable", "text/plain; charset=utf-8")


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT, open_browser: bool = False) -> int:
    info = prepare()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.info = info  # type: ignore[attr-defined]
    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}/"
    print("Démo RGAA Agent")
    print(f"  avant {info['baseline']['percent']} % · après {info['score']['percent']} % · {info['patches']} corrections")
    print(f"  {url}")
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
