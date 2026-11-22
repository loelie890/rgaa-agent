"""Interface en ligne de commande de RGAA Agent."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from . import kernel
from .kernel import CAMPAGNE_DIR, Ctx, Registry, Sandbox, SkillsStore
from .planners import list_models
from .tools import build_registry

TEMPLATE_CAMPAGNE = {
    "title": "Nouveau campagne",
    "objective": "Décrire l'objectif confié à l'agent en une phrase.",
    "as_of": "2026-12-01",
    "budget": 14,
    "passes": [{"label": "passe unique", "cassette": "cassette.json"}],
}
TEMPLATE_CASSETTE = {
    "steps": [
        {"thought": "Commencer par lister le classeur.", "tool": "fs_list", "args": {"dir": "."}},
        {"thought": "Conclusion.", "final": "À compléter."},
    ]
}


def _fmt_size(size: int) -> str:
    return f"{size} o" if size < 1024 else f"{size / 1024:.1f} ko"


def _probe_registry() -> Registry:
    """Registre jetable, utilisé pour valider les cassettes hors exécution."""
    tmp = Path(tempfile.mkdtemp(prefix="archiviste-validate-"))
    ctx = Ctx(sandbox=Sandbox(tmp / "sandbox"), as_of=dt.date.today(), skills=SkillsStore(tmp / "skills"), campagne="_validate")
    registry = Registry()
    build_registry(registry, ctx)
    ctx.registry = registry
    return registry


def signature_params(signature: str) -> tuple[list[str], list[str]]:
    inner = signature[signature.index("(") + 1 : signature.rindex(")")]
    required: list[str] = []
    optional: list[str] = []
    for part in (p.strip() for p in inner.split(",")):
        if not part:
            continue
        name = part.split("=")[0].strip().replace("[]", "")
        if "=" in part or part.endswith("=None"):
            optional.append(name)
        else:
            required.append(name)
    return required, optional


def validate_campagnes() -> list[str]:
    registry = _probe_registry()
    problems: list[str] = []

    for scen in kernel.list_campagnes():
        slug = scen["slug"]
        base = CAMPAGNE_DIR / slug
        for entry in kernel.load_campagne(slug)["passes"]:
            cassette_rel = entry.get("cassette", "cassette.json")
            cassette_path = base / cassette_rel
            label = f"{slug}/{cassette_rel}"
            if not cassette_path.is_file():
                problems.append(f"{label} : cassette absente")
                continue
            try:
                payload = json.loads(cassette_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                problems.append(f"{label} : JSON invalide ({exc})")
                continue
            steps = payload.get("steps", payload) if isinstance(payload, dict) else payload
            if not isinstance(steps, list) or not steps:
                problems.append(f"{label} : cassette vide")
                continue
            if "final" not in (steps[-1] or {}):
                problems.append(f"{label} : la dernière étape doit être un 'final'")
            for index, step in enumerate(steps, start=1):
                if not isinstance(step, dict):
                    problems.append(f"{label} étape {index} : objet JSON attendu")
                    continue
                if "final" in step:
                    continue
                tool_name = step.get("tool")
                args = step.get("args", {})
                tool = registry.get(tool_name) if isinstance(tool_name, str) else None
                if tool is None:
                    problems.append(f"{label} étape {index} : outil inconnu {tool_name!r}")
                    continue
                required, optional = signature_params(tool.signature())
                if not isinstance(args, dict):
                    problems.append(f"{label} étape {index} : args doit être un objet")
                    continue
                missing = [p for p in required if p not in args]
                extra = [k for k in args if k not in required and k not in optional]
                if missing:
                    problems.append(f"{label} étape {index} : argument(s) manquant(s) {missing} pour {tool.signature()}")
                if extra:
                    problems.append(f"{label} étape {index} : argument(s) inconnu(s) {extra} pour {tool.signature()}")
    return problems


def cmd_list(_: argparse.Namespace) -> int:
    for scen in kernel.list_campagnes():
        flag = "apprentissage" if scen["learning"] else "simple"
        print(f"{scen['slug']:<14} {flag:<14} budget {scen['budget']:>2} · {len(scen['fixtures'])} doc(s) · {scen['title']}")
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    problems = validate_campagnes()
    if problems:
        print(f"{len(problems)} problème(s) de cassette :")
        for problem in problems:
            print(f"  ✗ {problem}")
        return 1
    count = sum(len(kernel.load_campagne(s["slug"])["passes"]) for s in kernel.list_campagnes())
    print(f"✓ {count} cassette(s) valides : outils connus, arguments conformes, conclusion présente.")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    slug = args.slug.strip().lower()
    target = CAMPAGNE_DIR / slug
    if target.exists():
        print(f"✗ {target} existe déjà", file=sys.stderr)
        return 1
    (target / "fixtures").mkdir(parents=True)
    (target / "fixtures" / ".gitkeep").write_text("", encoding="utf-8")
    (target / "campagne.json").write_text(json.dumps({**TEMPLATE_CAMPAGNE, "slug": slug}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (target / "cassette.json").write_text(json.dumps(TEMPLATE_CASSETTE, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"✓ campagne créé : {target}")
    print("  1. déposer les documents de test dans fixtures/")
    print("  2. décrire l'objectif dans campagne.json")
    print("  3. écrire la cassette puis vérifier : python -m archiviste validate")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    live = None
    if args.live:
        live = {"base_url": args.base_url, "model": args.model, "api_key": args.api_key, "timeout": args.timeout}
    vision = {
        "base_url": args.vision_url or os.environ.get("RGAA_VISION_URL"),
        "model": args.vision_model or os.environ.get("RGAA_VISION_MODEL"),
        "api_key": args.vision_key or os.environ.get("RGAA_VISION_KEY"),
    }
    started = time.perf_counter()
    try:
        result = kernel.run_campagne(
            args.campagne,
            mode="live" if args.live else "replay",
            live=live,
            as_of=args.as_of,
            max_steps=args.steps,
            vision=vision,
        )
    except FileNotFoundError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    elapsed = time.perf_counter() - started

    if getattr(args, "publish", None):
        from .publish import publish as publish_run

        meta = publish_run(
            result,
            Path(result["run_dir"]),
            args.publish,
            duration_s=elapsed,
            model=args.model if args.live else None,
            vision_model=vision.get("model"),
        )
        print(
            f"Publié     : {args.publish} · {meta['duree_s']} s mesurées, "
            f"{meta['etapes']} étapes, {meta['par_etape_s']} s par étape"
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "done" else 1

    print(f"Campagne   : {result['title']} ({result['campagne']})")
    print(f"Objectif   : {result['objective']}")
    print(f"Mode       : {'live ' + args.model if args.live else 'replay (déterministe, aucun réseau)'}")
    print(f"Référence  : {result['as_of']} · budget {result['budget']} étapes")
    print()
    for entry in result["passes"]:
        if len(result["passes"]) > 1:
            print(f"── {entry['label']} ──")
        for record in entry["records"]:
            mark = "✓" if record["ok"] else "✗"
            args_txt = json.dumps(record["args"], ensure_ascii=False)
            print(f"{record['step']:>2} {mark} {record['tool']}({args_txt[:96]})")
            observation = record["observation"]
            detail = observation.get("error") if not observation.get("ok") else _summarize(observation.get("result"))
            if detail:
                print(f"      → {detail[:150]}")
        print(f"   conclusion : {entry['final'][:220]}")
        print()
    print(f"Statut     : {result['status']} · {sum(p['steps'] for p in result['passes'])} étapes · {result['errors']} erreur(s)")
    if result["artifacts"]:
        print("Artefacts  :")
        for artifact in result["artifacts"]:
            print(f"  - {artifact['name']} ({_fmt_size(artifact['bytes'])})")
    if len(result["passes"]) > 1:
        left, right = result["passes"][0], result["passes"][1]
        gain = left["steps"] - right["steps"]
        print()
        print(
            f"Apprentissage : {left['label']} → {left['steps']} étapes · {left['errors']} erreur(s) | "
            f"{right['label']} → {right['steps']} étapes · {right['errors']} erreur(s)"
            + (f" ({gain} étape(s) en moins)" if gain > 0 else "")
        )
    if result["skills"]:
        print(f"Procédures apprises : {', '.join(s['slug'] for s in result['skills'])}")
    print(f"Journal    : {result['journal']}")
    return 0 if result["status"] == "done" else 1


def _summarize(result: object, width: int = 130) -> str:
    if result is None:
        return ""
    if isinstance(result, dict):
        for key in ("count", "written", "added", "alerts", "files", "hits", "rows", "total"):
            if key in result:
                return f"{key}={result[key]}"
        return json.dumps(result, ensure_ascii=False)[:width]
    return str(result)[:width]


def cmd_ci(args: argparse.Namespace) -> int:
    from .ci import run_ci

    try:
        result = run_ci(
            Path(args.site),
            min_score=args.min_score,
            write=args.write,
            diff_path=Path(args.diff) if args.diff else None,
            report_path=Path(args.report) if args.report else None,
            lang=args.lang,
            vision={"base_url": args.vision_url, "model": args.vision_model},
        )
    except FileNotFoundError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = {key: value for key, value in result.items() if key != "diff"}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return result["exit_code"]

    before, after = result["baseline"], result["score"]
    print(f"Site        : {result['site']} ({len(result['pages'])} page(s))")
    print(
        f"Score audit : {before['percent']} % (note {before['grade']['letter']}) → "
        f"{after['percent']} % (note {after['grade']['letter']}) · {after['violations']} violation(s) restante(s)"
    )
    print(f"Corrections : {len(result['patches'])} appliquée(s), dont {len(result['review'])} à relire")
    if result.get("vision", {}).get("available"):
        vision_info = result["vision"]
        print(
            f"Vision      : {vision_info['images']} image(s) analysée(s), "
            f"{vision_info['findings']} constat(s), {vision_info['fixes']} alternative(s) écrite(s)"
        )
    for patch in result["review"][:6]:
        print(f"  ~ {patch['page']} {patch['selector']} : {patch['op']}")
    if result["diff_path"]:
        lines = result["diff"].count("\n")
        print(f"Diff        : {result['diff_path']} ({lines} ligne(s) unifiée(s))")
    if args.write:
        print("Écriture    : pages corrigées sur place")
    if result["report_path"]:
        print(f"Rapport     : {result['report_path']}")
    state = "OK" if result["passed"] else "ÉCHEC"
    print(f"Seuil       : {result['min_score']} % → {state} (code de sortie {result['exit_code']})")
    for finding in result["findings"][:10]:
        print(f"  ✗ {finding['rule']} · {finding['page']} · {finding['selector']} : {finding['message'][:110]}")
    return int(result["exit_code"])


def cmd_cost(args: argparse.Namespace) -> int:
    from .cost import compare, render

    result = compare(
        steps=args.steps,
        tokens_in=args.tokens_in,
        tokens_out=args.tokens_out,
        price_in=args.price_in,
        price_out=args.price_out,
        watts=args.watts,
        kwh_price=args.kwh,
        seconds_per_audit=args.seconds,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(render(result))
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    import shutil
    import tempfile

    from .ci import run_ci
    from .remote import RemoteError, fetch, save

    workdir = Path(tempfile.mkdtemp(prefix="rgaa-scan-"))
    try:
        page = fetch(args.url, allow_private=args.allow_private)
    except RemoteError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    save(page, workdir)
    report = workdir / "deliverables" / "rapport-rgaa.html"
    vision = {"base_url": args.vision_url, "model": args.vision_model}
    result = run_ci(workdir, min_score=args.min_score, write=args.write, report_path=report, vision=vision, base_url=args.url)
    print(f"Page        : {args.url} ({page['bytes']} octets, HTTP {page['status']})")
    print(
        f"Score audit : {result['baseline']['percent']} % (note {result['baseline']['grade']['letter']}, "
        f"{result['baseline']['grade']['label']}) → {result['score']['percent']} % "
        f"(note {result['score']['grade']['letter']}, {result['score']['grade']['label']})"
    )
    print(f"Violations  : {result['baseline']['violations']} → {result['score']['violations']}")
    print(f"Corrections : {len(result['patches'])}, dont {len(result['review'])} à relire")
    if result.get("vision", {}).get("available"):
        vision_info = result["vision"]
        print(
            f"Vision      : {vision_info['images']} image(s) analysée(s), "
            f"{vision_info['findings']} constat(s), {vision_info['fixes']} alternative(s) écrite(s)"
        )
    else:
        print("Vision      : non configurée (--vision-url et --vision-model)")
    if args.browser:
        from . import browser, browser_audit

        try:
            rendered = browser.render(url=args.url, mode=args.browser_mode, budget_ms=4000, timeout=150.0)
        except browser.BrowserError as exc:
            print(f"Navigateur  : indisponible ({exc})")
        else:
            (workdir / "deliverables").mkdir(parents=True, exist_ok=True)
            rendered_path = workdir / f"rendu-{page['name']}"
            rendered_path.write_text(browser.strip_report(rendered.html), encoding="utf-8")
            browser_result = browser_audit.analyse(rendered.report, page["name"])
            (workdir / "deliverables" / "rendu-navigateur.json").write_text(
                json.dumps(browser_result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"Navigateur  : {rendered.mode}, {rendered.ms} ms · {browser_audit.summary(browser_result)}")
            for row in browser_result["findings"][:6]:
                print(f"  {row['criterion']:<5} {row['severity']:<9} {row['message'][:70]}")
    print(f"Rapport     : {report}")
    if args.out:
        shutil.copytree(workdir, args.out, dirs_exist_ok=True)
        print(f"Copie       : {args.out}")
    return 0 if result["passed"] else 1


def cmd_render(args: argparse.Namespace) -> int:
    from . import browser, browser_audit

    try:
        rendered = browser.render(
            url=args.url, path=args.page, mode=args.mode, budget_ms=args.budget
        )
    except browser.BrowserError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(browser.strip_report(rendered.html), encoding="utf-8")
    result = browser_audit.analyse(rendered.report, args.url or str(args.page) or "page")
    print(f"Rendu    : {rendered.mode}, {rendered.ms} ms, {len(rendered.html)} octets de DOM")
    print(f"Constats : {browser_audit.summary(result)}")
    for row in result["findings"][: args.limit]:
        print(f"  {row['criterion']:<5} {row['severity']:<9} {row['selector'][:36]:<36} {row['message'][:64]}")
    if len(result["findings"]) > args.limit:
        print(f"  … {len(result['findings']) - args.limit} autre(s), voir --json")
    if args.out:
        print(f"Copie    : {args.out}")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    from . import coverage

    data = coverage.matrix()
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else coverage.render_text(data))
    return 0


def cmd_fit(args: argparse.Namespace) -> int:
    from . import fit

    data = fit.fit(
        vram_gb=args.vram,
        vram_actuelle=args.vram_actuelle,
        context=args.contexte,
        images=args.images,
        seconds_per_image=args.secondes,
    )
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else fit.render_text(data))
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from . import mcp

    return mcp.serve()


def cmd_team(args: argparse.Namespace) -> int:
    from .team import apply_report, run_team

    try:
        team = run_team(
            Path(args.site),
            workers=args.workers,
            write=args.write,
            vision={"base_url": args.vision_url, "model": args.vision_model},
        )
    except FileNotFoundError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    before, after = team["baseline"], team["score"]
    print(f"Sous-agents : {team['workers']} en parallèle · {team['ms']} ms")
    print(f"{'agent':<18}{'rôle':<14}{'page':<16}{'avant':>7}{'après':>7}{'patch':>7}{'ms':>7}")
    for agent in team["agents"]:
        print(
            f"{agent['agent']:<18}{agent['role']:<14}{agent['page']:<16}"
            f"{agent['before']:>6.1f}%{agent['after']:>6.1f}%{agent['patches']:>7}{agent['ms']:>7}"
        )
    print(
        f"Global      : {before['percent']} % (note {before['grade']['letter']}) → "
        f"{after['percent']} % (note {after['grade']['letter']}) · {team['patches']} correction(s)"
    )
    if team.get("vision", {}).get("available"):
        vision_info = team["vision"]
        print(
            f"Vision      : {vision_info['images']} image(s) analysée(s), "
            f"{vision_info['findings']} constat(s), {vision_info['fixes']} alternative(s) écrite(s)"
        )
    if args.report:
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        apply_report(team, target.parent)
        print(f"Rapport     : {target}")
    return 0 if after["percent"] >= args.min_score else 1


def cmd_export(args: argparse.Namespace) -> int:
    from .export import build_zip

    run_dir = Path(kernel.RUNS_DIR) / args.run
    if not run_dir.is_dir():
        print(f"✗ run inconnu : {args.run}", file=sys.stderr)
        return 2
    target = Path(args.out or f"{args.run}.zip")
    target.write_bytes(build_zip(run_dir))
    print(f"Export      : {target} ({target.stat().st_size} octets)")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from .demo import serve as serve_demo

    return serve_demo(host=args.host, port=args.port, open_browser=args.open)


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    return serve(host=args.host, port=args.port, open_browser=args.open)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rgaa", description="Agent local de mise en conformité RGAA 4.1.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="lister les campagnes").set_defaults(func=cmd_list)
    sub.add_parser("validate", help="valider les cassettes contre les signatures d'outils").set_defaults(func=cmd_validate)

    new = sub.add_parser("new", help="créer un nouveau campagne")
    new.add_argument("slug")
    new.set_defaults(func=cmd_new)

    run = sub.add_parser("run", help="exécuter un campagne")
    run.add_argument("campagne")
    run.add_argument("--live", action="store_true", help="utiliser un backend OpenAI-compatible au lieu de la cassette")
    run.add_argument("--base-url", default="http://127.0.0.1:11434", help="URL du backend (ollama par défaut)")
    run.add_argument("--model", default="qwen2.5-coder:7b")
    run.add_argument("--api-key", default=None)
    run.add_argument("--timeout", type=int, default=180)
    run.add_argument("--as-of", default=None, help="date de référence AAAA-MM-JJ (défaut : aujourd'hui)")
    run.add_argument("--steps", type=int, default=None, help="budget d'étapes")
    run.add_argument("--vision-url", default=None, help="endpoint d'un modèle vision local (RGAA_VISION_URL)")
    run.add_argument("--vision-model", default=None, help="nom du modèle vision (RGAA_VISION_MODEL)")
    run.add_argument("--vision-key", default=None, help="clé éventuelle du backend vision (RGAA_VISION_KEY)")
    run.add_argument("--publish", default=None, help="écrire journal, transcription et méta mesurée dans ce dossier")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_run)

    ci = sub.add_parser("ci", help="audit et corrections déterministes, avec code de sortie strict")
    ci.add_argument("site", nargs="?", default=".", help="dossier contenant les pages HTML")
    ci.add_argument("--min-score", type=float, default=100.0, help="seuil de conformité exigé (défaut 100)")
    ci.add_argument("--write", action="store_true", help="écrit les corrections dans les fichiers")
    ci.add_argument("--diff", default="rgaa.patch.diff", help="chemin du diff unifié produit")
    ci.add_argument("--report", default=None, help="écrit aussi un rapport HTML à ce chemin")
    ci.add_argument("--lang", default="fr", help="langue appliquée quand elle manque")
    ci.add_argument("--vision-url", default=None, help="endpoint du modèle vision (RGAA_VISION_URL)")
    ci.add_argument("--vision-model", default=None, help="modèle vision (RGAA_VISION_MODEL)")
    ci.add_argument("--json", action="store_true")
    ci.set_defaults(func=cmd_ci)

    serve = sub.add_parser("serve", help="lancer l'interface web locale")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--open", action="store_true", help="ouvrir le navigateur")
    serve.set_defaults(func=cmd_serve)

    demo = sub.add_parser("demo", help="site de démonstration avant/après côte à côte")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8090)
    demo.add_argument("--open", action="store_true", help="ouvrir le navigateur")
    demo.set_defaults(func=cmd_demo)

    cost = sub.add_parser("cost", help="comparer le coût local et le coût cloud, hypothèses affichées")
    cost.add_argument("--steps", type=int, default=24)
    cost.add_argument("--tokens-in", type=int, default=1000, dest="tokens_in")
    cost.add_argument("--tokens-out", type=int, default=80, dest="tokens_out")
    cost.add_argument("--price-in", type=float, default=0.15, dest="price_in")
    cost.add_argument("--price-out", type=float, default=0.60, dest="price_out")
    cost.add_argument("--seconds", type=float, default=0.45)
    cost.add_argument("--watts", type=float, default=65.0)
    cost.add_argument("--kwh", type=float, default=0.25)
    cost.add_argument("--json", action="store_true")
    cost.set_defaults(func=cmd_cost)

    scan = sub.add_parser("scan", help="analyser directement une URL publique")
    scan.add_argument("url")
    scan.add_argument("--min-score", type=float, default=100.0, dest="min_score")
    scan.add_argument("--write", action="store_true", help="écrire les corrections dans la copie locale")
    scan.add_argument("--out", default=None, help="copier le résultat dans ce dossier")
    scan.add_argument("--allow-private", action="store_true", dest="allow_private", help="autoriser localhost et adresses privées")
    scan.add_argument("--vision-url", default=None, help="endpoint du modèle vision (RGAA_VISION_URL)")
    scan.add_argument("--vision-model", default=None, help="modèle vision (RGAA_VISION_MODEL)")
    scan.add_argument("--browser", action="store_true", help="ouvrir la page dans Chromium et mesurer le DOM rendu")
    scan.add_argument("--browser-mode", default=None, choices=["headless", "headful"], dest="browser_mode")
    scan.set_defaults(func=cmd_scan)

    render = sub.add_parser("render", help="rendre une page dans Chromium et mesurer ce que JavaScript produit")
    render.add_argument("url", nargs="?", default=None, help="adresse de la page")
    render.add_argument("--page", default=None, help="fichier HTML local, à la place de l'URL")
    render.add_argument("--mode", choices=["headless", "headful"], default=None)
    render.add_argument("--budget", type=int, default=4000, help="millisecondes laissées à la page")
    render.add_argument("--out", default=None, help="écrire le DOM rendu dans ce fichier")
    render.add_argument("--limit", type=int, default=12)
    render.add_argument("--json", action="store_true")
    render.set_defaults(func=cmd_render)

    cov = sub.add_parser("coverage", help="les 106 critères RGAA et le statut de chacun")
    cov.add_argument("--json", action="store_true")
    cov.set_defaults(func=cmd_coverage)

    fitt = sub.add_parser("fit", help="ce qui tient dans une mémoire donnée, et ce que ça change ici")
    fitt.add_argument("--vram", type=float, default=32.0, help="mémoire visée, en Go (32 par défaut)")
    fitt.add_argument("--vram-actuelle", type=float, default=4.0, dest="vram_actuelle", help="mémoire de la machine actuelle")
    fitt.add_argument("--contexte", type=int, default=8192)
    fitt.add_argument("--images", type=int, default=None, help="images par audit (fixtures par défaut)")
    fitt.add_argument("--secondes", type=float, default=4.0, help="secondes par image")
    fitt.add_argument("--json", action="store_true")
    fitt.set_defaults(func=cmd_fit)

    mcp = sub.add_parser("mcp", help="servir les outils en MCP, sur l'entrée et la sortie standard")
    mcp.set_defaults(func=cmd_mcp)

    team = sub.add_parser("team", help="répartir les corrections entre sous-agents, une page chacun")
    team.add_argument("site", nargs="?", default="fixtures/site")
    team.add_argument("--workers", type=int, default=None)
    team.add_argument("--min-score", type=float, default=100.0, dest="min_score")
    team.add_argument("--write", action="store_true")
    team.add_argument("--report", default=None, help="écrire le rapport HTML à ce chemin")
    team.add_argument("--vision-url", default=None, help="endpoint du modèle vision (RGAA_VISION_URL)")
    team.add_argument("--vision-model", default=None, help="modèle vision (RGAA_VISION_MODEL)")
    team.set_defaults(func=cmd_team)

    export = sub.add_parser("export", help="exporter un run en archive ZIP")
    export.add_argument("run")
    export.add_argument("--out", default=None)
    export.set_defaults(func=cmd_export)

    bench = sub.add_parser("rules", help="afficher les 12 règles et leurs critères RGAA")
    bench.set_defaults(func=lambda a: _print_rules())

    models = sub.add_parser("models", help="sonder un backend : liste les modèles exposés")
    models.add_argument("--base-url", default="http://127.0.0.1:11434")
    models.set_defaults(func=lambda a: _print_models(a.base_url))
    return parser


def _print_models(base_url: str) -> int:
    try:
        payload = list_models(base_url)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ backend injoignable sur {base_url} : {exc}", file=sys.stderr)
        return 1
    print(f"Endpoint normalisé : {payload['base_url']}")
    for model in payload["models"]:
        print(f"  - {model}")
    return 0


def _print_rules() -> int:
    from .audit import RULES

    print(f"{len(RULES)} règles vérifiées mécaniquement (RGAA 4.1) :")
    for rule in RULES:
        print(f"  {rule.id:<15} {rule.rgpa:<6} {rule.severity:<9} {rule.label}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
