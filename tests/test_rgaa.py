"""Suite de tests — unittest seul, aucun service externe requis.

Couvre : validation des cassettes, exécution de tous les campagnes, conformité
réellement atteinte, refus de sortie du bac à sable, budget, sélecteurs, patchs,
sérialisation, calcul de contraste, API HTTP et charset.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

_TMP = Path(tempfile.mkdtemp(prefix="rgaa-tests-"))
os.environ.setdefault("RGAA_RUNS", str(_TMP / "runs"))
os.environ.setdefault("RGAA_DATA", str(_TMP / "data"))

from rgaa import cli, demo, kernel, server  # noqa: E402
from rgaa.audit import RULES, audit_page, audit_site, contrast_ratio, score  # noqa: E402
from rgaa.ci import run_ci  # noqa: E402
from rgaa.css import propose_compliant, resolve_text_style  # noqa: E402
from rgaa.dom import Document, DomError, apply_patch, parse, select  # noqa: E402
from rgaa.export import build_zip  # noqa: E402
from rgaa.kernel import Ctx, Registry, Sandbox, SkillsStore  # noqa: E402
from rgaa.remote import RemoteError, fetch as fetch_url, save  # noqa: E402
from rgaa.team import apply_report, run_team  # noqa: E402
from rgaa.tools import build_registry  # noqa: E402
from rgaa.vision import describe_image  # noqa: E402

RUNS = Path(os.environ["RGAA_RUNS"])
SITE = BASE / "fixtures" / "site"


def load_site() -> dict[str, Document]:
    return {path.name: parse(path.read_text(encoding="utf-8")) for path in sorted(SITE.glob("*.html"))}


def make_ctx() -> tuple[Registry, Ctx]:
    root = Path(tempfile.mkdtemp(prefix="rgaa-ctx-", dir=_TMP))
    sandbox = Sandbox(root / "sandbox")
    for page in list(SITE.glob("*.html")) + list(SITE.glob("*.png")):
        (sandbox.root / page.name).write_bytes(page.read_bytes())
    ctx = Ctx(
        sandbox=sandbox,
        as_of=__import__("datetime").date(2026, 11, 20),
        skills=SkillsStore(root / "skills"),
        campagne="_test",
    )
    registry = Registry()
    build_registry(registry, ctx)
    ctx.registry = registry
    return registry, ctx


class TestDom(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = parse(
            "<html lang='fr'><body><ul id='l'><li class='a'>un</li><li class='b'>deux</li></ul>"
            "<img id='i' src='x.png'><a href='#'><img alt=''></a></body></html>"
        )

    def test_select_tag(self) -> None:
        self.assertEqual(len(select(self.doc.root, "li")), 2)

    def test_select_class_and_id(self) -> None:
        self.assertEqual(len(select(self.doc.root, ".a")), 1)
        self.assertEqual(len(select(self.doc.root, "#i")), 1)
        self.assertEqual(len(select(self.doc.root, "img#i")), 1)

    def test_select_attribute(self) -> None:
        self.assertEqual(len(select(self.doc.root, "img[alt]")), 1)
        self.assertEqual(len(select(self.doc.root, "img[alt='']")), 1)

    def test_select_descendant_and_child(self) -> None:
        self.assertEqual(len(select(self.doc.root, "ul li")), 2)
        self.assertEqual(len(select(self.doc.root, "ul > li")), 2)
        self.assertEqual(len(select(self.doc.root, "body > li")), 0)

    def test_select_first_child(self) -> None:
        nodes = select(self.doc.root, "li:first-child")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].text(), "un")

    def test_unknown_selector_raises(self) -> None:
        with self.assertRaises(DomError):
            select(self.doc.root, "li:banana")

    def test_roundtrip_and_escapes(self) -> None:
        doc = parse("<html><body><p>a &amp; b</p><img src='x'></body></html>")
        markup = doc.serialize()
        self.assertIn("a &amp; b", markup)
        again = parse(markup)
        self.assertEqual(again.root.text().strip(), "a & b")

    def test_patch_set_attr_all_matches(self) -> None:
        result = apply_patch(self.doc, "ul > li", "set_attr", name="role", value="listitem")
        self.assertEqual(result["changed"], 2)

    def test_patch_set_tag_and_text(self) -> None:
        apply_patch(self.doc, "li", "set_tag", value="div")
        self.assertEqual(len(select(self.doc.root, "div")), 2)
        apply_patch(self.doc, "img#i", "set_attr", name="alt", value="photo")
        self.assertIn("alt=\"photo\"", select(self.doc.root, "img#i")[0].snippet())

    def test_patch_insert_html_before(self) -> None:
        apply_patch(self.doc, "img#i", "insert_html", name="before", value="<label for='i'>Étiquette</label>")
        self.assertEqual(len(select(self.doc.root, "label")), 1)

    def test_patch_noop_refused(self) -> None:
        with self.assertRaises(DomError) as ctx:
            apply_patch(self.doc, "img#i", "set_attr", name="src", value="x.png")
        self.assertIn("aucun changement", str(ctx.exception))

    def test_patch_unknown_op_and_selector(self) -> None:
        with self.assertRaises(DomError):
            apply_patch(self.doc, "img#i", "explode")
        with self.assertRaises(DomError):
            apply_patch(self.doc, "#absent", "set_attr", name="x", value="y")


class TestAudit(unittest.TestCase):
    def test_fixture_audit_finds_all_rules(self) -> None:
        findings = audit_site(load_site())
        self.assertEqual(len(findings), 16)
        violated = {finding.rule for finding in findings}
        self.assertEqual(violated, {rule.id for rule in RULES})

    def test_score_before_fixes(self) -> None:
        summary = score(load_site())
        self.assertEqual(summary["checks"], 48)
        self.assertEqual(summary["conform"], 34)
        self.assertEqual(summary["percent"], 70.8)

    def test_contrast_maths(self) -> None:
        self.assertAlmostEqual(contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, places=1)
        self.assertAlmostEqual(contrast_ratio((255, 255, 255), (255, 255, 255)), 1.0, places=2)

    def test_conforming_page_has_no_finding(self) -> None:
        doc = parse((BASE / "fixtures" / "site" / "contact.html").read_text(encoding="utf-8"))
        self.assertEqual(audit_site({"contact.html": doc}), [])


    def test_grade_letters(self) -> None:
        from rgaa.audit import grade

        self.assertEqual(grade(100)["letter"], "A")
        self.assertEqual(grade(70.8)["letter"], "C")
        self.assertEqual(grade(33.3)["letter"], "E")
        self.assertEqual(score(load_site())["grade"]["letter"], "C")


class TestTools(unittest.TestCase):
    def setUp(self) -> None:
        self.registry, self.ctx = make_ctx()

    def test_audit_run_returns_selectors(self) -> None:
        out = self.registry.call("audit_run", {})
        self.assertTrue(out["ok"])
        self.assertEqual(out["result"]["violations"], 16)
        self.assertTrue(all(item["selector"] for item in out["result"]["findings"]))

    def test_patch_updates_file_and_score(self) -> None:
        out = self.registry.call(
            "patch_html", {"page": "index.html", "selector": "html", "op": "set_attr", "name": "lang", "value": "fr"}
        )
        self.assertTrue(out["ok"], out)
        self.assertIn('lang="fr"', (self.ctx.sandbox.root / "index.html").read_text(encoding="utf-8"))
        after = self.registry.call("audit_run", {"page": "index.html"})
        self.assertLess(after["result"]["violations"], 15)

    def test_patch_on_missing_page(self) -> None:
        out = self.registry.call("patch_html", {"page": "absent.html", "selector": "html", "op": "set_attr", "name": "lang", "value": "fr"})
        self.assertFalse(out["ok"])
        self.assertIn("introuvable", out["error"])

    def test_html_query(self) -> None:
        out = self.registry.call("html_query", {"page": "produits.html", "selector": "table.catalog tr:first-child td"})
        self.assertEqual(out["result"]["count"], 2)

    def test_sandbox_escape(self) -> None:
        out = self.registry.call("html_query", {"page": "../../etc/passwd", "selector": "html"})
        self.assertFalse(out["ok"])
        self.assertIn("bac à sable", out["error"])

    def test_unknown_tool_and_bad_args(self) -> None:
        self.assertIn("outil inconnu", self.registry.call("rm_rf", {})["error"])
        self.assertIn("manquants", self.registry.call("patch_html", {})["error"])
        self.assertIn("inconnus", self.registry.call("site_list", {"verbose": True})["error"])


class TestCampagnes(unittest.TestCase):
    def test_validate(self) -> None:
        self.assertEqual(cli.validate_campagnes(), [])

    def test_all_campagnes(self) -> None:
        for scen in kernel.list_campagnes():
            with self.subTest(campagne=scen["slug"]):
                result = kernel.run_campagne(scen["slug"], runs_dir=RUNS)
                self.assertEqual(result["status"], "done")
                if scen["learning"]:
                    first, second = result["passes"]
                    self.assertEqual((first["steps"], first["errors"]), (7, 1))
                    self.assertEqual((second["steps"], second["errors"]), (5, 0))
                    self.assertGreaterEqual(first["steps"] - second["steps"], 2)  # écart exigé par la démonstration
                else:
                    self.assertEqual(result["errors"], 0)

    def test_conformite_reaches_full_score(self) -> None:
        result = kernel.run_campagne("conformite", runs_dir=RUNS)
        self.assertEqual(result["errors"], 0)
        report = kernel.read_artifact(result["run_id"], "deliverables/audit-rgaa.md", RUNS).read_text(encoding="utf-8")
        self.assertIn("48/48", report)
        self.assertIn("100.0 %", report)
        patches = json.loads(kernel.read_artifact(result["run_id"], "rgaa-patches.json", RUNS).read_text(encoding="utf-8"))
        self.assertEqual(len(patches), 15)
        page = kernel.read_artifact(result["run_id"], "index.html", RUNS).read_text(encoding="utf-8")
        self.assertIn('lang="fr"', page)
        self.assertNotIn("<h3", page)

    def test_budget_enforced(self) -> None:
        result = kernel.run_campagne("conformite", max_steps=4, runs_dir=RUNS)
        self.assertEqual(result["status"], "budget")
        self.assertEqual(len(result["steps"]), 4)

    def test_refusal_changes_nothing(self) -> None:
        result = kernel.run_campagne("garde-fous", runs_dir=RUNS)
        self.assertIn("Je ne fais ni l'un ni l'autre", result["final"])
        self.assertEqual(result["artifacts"], [])


class TestCssContrast(unittest.TestCase):
    """Critère 3.2 sur les règles CSS internes, pas seulement les styles en ligne."""

    def test_stylesheet_contrast_detected(self) -> None:
        document = parse((SITE / "tarifs.html").read_text(encoding="utf-8"))
        findings = [finding for finding in audit_page("tarifs.html", document) if finding.rule == "contrast"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].selector, "p.tarif-note")
        self.assertIn("2.34", findings[0].message)

    def test_cascade_and_background_inheritance(self) -> None:
        document = parse(
            "<html lang='fr'><head><style>.box{color:#777777;background-color:#1b1f24}"
            ".box p{color:#eeeeee}</style></head><body><div class='box'><p>texte</p></div></body></html>"
        )
        style = resolve_text_style(document, select(document.root, "p")[0])
        self.assertEqual(style["color"], "#eeeeee")
        self.assertEqual(style["background"], "#1b1f24")

    def test_propose_compliant_keeps_hue_and_reaches_threshold(self) -> None:
        proposal = propose_compliant("#a3aab3", "#ffffff", 4.5)
        self.assertTrue(proposal["changed"])
        self.assertGreaterEqual(proposal["ratio"], 4.5)
        unchanged = propose_compliant("#000000", "#ffffff", 4.5)
        self.assertFalse(unchanged["changed"])


class TestVision(unittest.TestCase):
    """Le contrat de `inspect_image`, vérifié contre un endpoint simulé."""

    @classmethod
    def setUpClass(cls) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # silence
                return

            def do_GET(self) -> None:  # noqa: N802
                body = json.dumps({"data": [{"id": "fake-vl"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = json.dumps(
                    {"choices": [{"message": {"content": "Une trottinette rouge pliée devant une vitrine."}}]}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_describe_with_simulated_vlm(self) -> None:
        result = describe_image(SITE / "hero.png", f"http://127.0.0.1:{self.port}", "fake-vl")
        self.assertTrue(result["available"])
        self.assertEqual(result["source"], "vlm-openai")
        self.assertIn("trottinette rouge", result["description"])
        self.assertLessEqual(len(result["description"]), 160)

    def test_explicit_fallback_without_model(self) -> None:
        result = describe_image(SITE / "hero.png", None, None)
        self.assertFalse(result["available"])
        self.assertEqual(result["source"], "fallback")
        self.assertIn("fallback_hint", result)

    def test_tool_uses_configured_vision(self) -> None:
        registry, ctx = make_ctx()
        ctx.vision = {"base_url": f"http://127.0.0.1:{self.port}", "model": "fake-vl"}
        out = registry.call("inspect_image", {"path": "hero.png"})
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["result"]["available"])

    def test_missing_image_is_an_observation(self) -> None:
        registry, _ = make_ctx()
        out = registry.call("inspect_image", {"path": "absente.png"})
        self.assertFalse(out["ok"])
        self.assertIn("introuvable", out["error"])


class TestHtmlReport(unittest.TestCase):
    def test_report_is_standalone_and_self_conforming(self) -> None:
        result = kernel.run_campagne("conformite", runs_dir=RUNS)
        markup = kernel.read_artifact(result["run_id"], "deliverables/rapport-rgaa.html", RUNS).read_text(encoding="utf-8")
        self.assertIn("Rapport d'accessibilité", markup)
        self.assertIn("<ins>", markup)
        self.assertIn("<del>", markup)
        self.assertNotIn("<script", markup)
        self.assertNotIn("rel=\"stylesheet\"", markup)
        # Le rapport applique les règles qu'il documente : 0 violation.
        self.assertEqual(audit_page("rapport.html", parse(markup)), [])


class TestCiMode(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rgaa-ci-", dir=_TMP))
        for page in SITE.glob("*.html"):
            (self.tmp / page.name).write_text(page.read_text(encoding="utf-8"), encoding="utf-8")

    def test_autofix_reaches_threshold_and_produces_diff(self) -> None:
        diff_path = self.tmp.parent / f"{self.tmp.name}.diff"
        result = run_ci(self.tmp, min_score=100, diff_path=diff_path)
        self.assertTrue(result["passed"])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["score"]["percent"], 100.0)
        self.assertEqual(result["baseline"]["percent"], 70.8)
        self.assertGreater(len(result["patches"]), 10)
        diff = diff_path.read_text(encoding="utf-8")
        self.assertIn("--- a/index.html", diff)
        self.assertIn("+++ b/tarifs.html", diff)
        self.assertNotIn("contact.html", diff, "une page déjà conforme ne doit pas être réécrite")
        self.assertTrue(result["review"], "les alt provisoires doivent être signalés à relire")

    def test_threshold_not_met_exits_1(self) -> None:
        result = run_ci(self.tmp, min_score=101)
        self.assertFalse(result["passed"])
        self.assertEqual(result["exit_code"], 1)

    def test_write_applies_to_disk(self) -> None:
        run_ci(self.tmp, min_score=100, write=True)
        page = (self.tmp / "index.html").read_text(encoding="utf-8")
        self.assertIn('lang="fr"', page)
        summary = score({path.name: parse(path.read_text(encoding="utf-8")) for path in self.tmp.glob("*.html")})
        self.assertEqual(summary["violations"], 0)

    def test_cli_returns_exit_code(self) -> None:
        code = cli.main(["ci", str(self.tmp), "--min-score", "100", "--diff", str(self.tmp.parent / "cli.diff")])
        self.assertEqual(code, 0)


class TestDemoMode(unittest.TestCase):
    """Le mode démo sert deux états réels du même site, plus le rapport."""

    @classmethod
    def setUpClass(cls) -> None:
        from http.server import ThreadingHTTPServer

        workspace = Path(tempfile.mkdtemp(prefix="rgaa-demo-", dir=_TMP)) / "workspace"
        cls.info = demo.prepare(workspace)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), demo.Handler)
        cls.httpd.info = cls.info  # type: ignore[attr-defined]
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path: str) -> bytes:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=20) as response:
            return response.read()

    def test_prepare_builds_both_states(self) -> None:
        self.assertEqual(self.info["baseline"]["percent"], 70.8)
        self.assertEqual(self.info["score"]["percent"], 100.0)
        self.assertEqual(self.info["patches"], 16)
        self.assertTrue(Path(self.info["report"]).is_file())

    def test_demo_page_and_score_endpoint(self) -> None:
        markup = self._get("/").decode("utf-8")
        self.assertIn("70.8", markup)
        self.assertIn("100.0", markup)
        payload = json.loads(self._get("/api/score"))
        self.assertEqual(payload["apres"]["violations"], 0)
        self.assertEqual(payload["avant"]["violations"], 16)

    def test_site_served_before_and_after(self) -> None:
        before = self._get("/site/avant/index.html").decode("utf-8")
        after = self._get("/site/apres/index.html").decode("utf-8")
        self.assertNotIn("<html lang", before)
        self.assertIn('<html lang="fr">', after)
        self.assertTrue(self._get("/site/apres/hero.png").startswith(b"\x89PNG"))

    def test_report_is_served(self) -> None:
        self.assertIn("Rapport d'accessibilité", self._get("/rapport.html").decode("utf-8"))


class TestCost(unittest.TestCase):
    def test_compare_is_arithmetic_not_magic(self) -> None:
        from rgaa.cost import compare, render

        result = compare(steps=10, tokens_in=1000, tokens_out=100, price_in=1.0, price_out=2.0)
        self.assertEqual(result["cloud"]["jetons_entree"], 10_000)
        self.assertAlmostEqual(result["cloud"]["par_audit"], 0.01 * 1.0 + 0.001 * 2.0, places=6)
        self.assertGreater(result["ratio"], 1)
        self.assertIn("électricité", render(result))


class TestTeamAndExport(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rgaa-team-", dir=_TMP))
        for page in SITE.glob("*.html"):
            (self.tmp / page.name).write_text(page.read_text(encoding="utf-8"), encoding="utf-8")

    def test_team_parallel_workers_reach_full_score(self) -> None:
        team = run_team(self.tmp, workers=4)
        self.assertEqual(team["workers"], 4)
        self.assertEqual(team["score"]["percent"], 100.0)
        self.assertEqual(len(team["agents"]), 4)
        self.assertTrue(all(agent["after"] == 100.0 for agent in team["agents"]))
        self.assertTrue(all(agent["role"] for agent in team["agents"]))
        self.assertGreaterEqual(sum(agent["patches"] for agent in team["agents"]), 10)

    def test_team_report_is_written(self) -> None:
        team = run_team(self.tmp)
        target = apply_report(team, self.tmp)
        self.assertTrue(target.is_file())
        self.assertIn("Rapport", target.read_text(encoding="utf-8"))

    def test_export_zip_contains_artifacts(self) -> None:
        run_dir = self.tmp / "run-demo"
        (run_dir / "sandbox" / "deliverables").mkdir(parents=True)
        (run_dir / "sandbox" / "deliverables" / "rapport.html").write_text("<html lang='fr'></html>", encoding="utf-8")
        (run_dir / "result.json").write_text('{"status": "done"}', encoding="utf-8")
        payload = build_zip(run_dir)
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
        self.assertIn("MANIFESTE.txt", names)
        self.assertIn("result.json", names)
        self.assertIn("sandbox/deliverables/rapport.html", names)


class TestScan(unittest.TestCase):
    def test_scan_local_page_over_http(self) -> None:
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

        handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=str(SITE), **kwargs)  # noqa: E731
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            page = fetch_url(f"http://127.0.0.1:{port}/index.html", allow_private=True)
            self.assertEqual(page["status"], 200)
            self.assertIn("<html", page["html"])
            workdir = Path(tempfile.mkdtemp(prefix="rgaa-scan-", dir=_TMP))
            save(page, workdir)
            result = run_ci(workdir, min_score=100, write=True)
            self.assertEqual(result["score"]["percent"], 100.0)
            self.assertGreater(len(result["patches"]), 5)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_private_host_refused_without_flag(self) -> None:
        with self.assertRaises(RemoteError):
            fetch_url("http://127.0.0.1:9/index.html")


class TestVisionAudit(unittest.TestCase):
    """La passe vision : verdicts et application réelle des alternatives proposées."""

    def test_classify_cases(self) -> None:
        from rgaa.vision_audit import classify

        analysis = {"available": True, "description": "Une trottinette rouge pliée devant une vitrine", "contains_text": False}
        self.assertEqual((classify(None, analysis) or {}).get("rule"), "vision-alt-absente")
        self.assertEqual((classify("photo", analysis) or {}).get("rule"), "vision-alt-generique")
        self.assertEqual((classify("hero", {**analysis, "src": "hero.png"}) or {}).get("rule"), "vision-alt-generique")
        self.assertIsNone(classify("Trottinette rouge pliée devant la boutique", analysis))
        self.assertEqual((classify("boutique", {**analysis, "contains_text": True}) or {}).get("rule"), "vision-texte-image")
        self.assertEqual((classify("logo", analysis) or {}).get("rule"), "vision-alt-generique")

    def test_ci_applies_vision_alternative(self) -> None:
        import rgaa.vision_audit as vision_audit

        original = vision_audit.analyse_image
        vision_audit.analyse_image = lambda *args, **kwargs: {
            "available": True,
            "source": "test",
            "description": "Trottinette rouge pliée devant une vitrine",
            "contains_text": False,
            "kind": "photo",
        }
        try:
            site = Path(tempfile.mkdtemp(prefix="rgaa-vision-", dir=_TMP))
            for page in list(SITE.glob("*.html")) + list(SITE.glob("*.png")):
                (site / page.name).write_bytes(page.read_bytes())
            result = run_ci(site, min_score=100, write=True, vision={"base_url": "http://127.0.0.1:1", "model": "fake-vl"})
        finally:
            vision_audit.analyse_image = original

        self.assertTrue(result["vision"]["available"])
        self.assertGreaterEqual(result["vision"]["images"], 3)
        self.assertEqual(result["vision"]["skipped"], 0)
        self.assertGreaterEqual(result["vision"]["fixes"], 1)
        index = (site / "index.html").read_text(encoding="utf-8")
        self.assertIn("Trottinette rouge pliée devant une vitrine", index)
        self.assertNotIn('alt="Hero"', index)
        sources = {patch.get("source") for patch in result["patches"]}
        self.assertIn("vision", sources)

    def test_no_vision_keeps_deterministic_fallback(self) -> None:
        site = Path(tempfile.mkdtemp(prefix="rgaa-novision-", dir=_TMP))
        for page in SITE.glob("*.html"):
            (site / page.name).write_text(page.read_text(encoding="utf-8"), encoding="utf-8")
        result = run_ci(site, min_score=100, write=True)
        self.assertFalse(result["vision"]["available"])
        self.assertIn('alt="Hero"', (site / "index.html").read_text(encoding="utf-8"))


class TestHttpApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=20) as response:
            return response.status, dict(response.headers), response.read()

    def test_healthz_and_index(self) -> None:
        status, _, body = self._get("/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        status, headers, body = self._get("/")
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("RGAA".encode(), body)

    def test_rules_endpoint(self) -> None:
        payload = json.loads(self._get("/api/rules")[2])
        self.assertEqual(len(payload["rules"]), 12)
        self.assertEqual(payload["rules"][0]["rgpa"], "8.3")

    def test_ci_endpoint(self) -> None:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/ci",
            data=json.dumps({"min_score": 100}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode())
        self.assertEqual(payload["baseline"]["percent"], 70.8)
        self.assertEqual(payload["score"]["percent"], 100.0)
        self.assertEqual(payload["exit_code"], 0)
        self.assertGreater(payload["diff_lines"], 10)

    def test_run_and_artifact(self) -> None:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/run",
            data=json.dumps({"campagne": "conformite", "mode": "replay"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode())
        self.assertEqual(result["status"], "done")
        status, headers, body = self._get(
            f"/api/artifact?run={result['run_id']}&name=deliverables/audit-rgaa.md"
        )
        self.assertEqual(status, 200)
        self.assertIn("charset=utf-8", headers["Content-Type"])
        self.assertIn("Conformité".encode("utf-8"), body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
