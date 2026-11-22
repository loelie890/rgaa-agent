"""Rendu navigateur et couverture des 106 critères.

Chrome n'est pas installé sur la machine de développement : la chaîne est donc
vérifiée contre un faux binaire qui imite `--dump-dom`. Ce qui est prouvé ici,
c'est le protocole (injection, récupération du rapport, calcul des constats) ;
l'exécution réelle d'un moteur est vérifiée à la main, avec Chrome installé.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from rgaa import browser, browser_audit, coverage

REPORT = {
    "title": "Page de test",
    "lang": "",
    "dir": "",
    "url": "file:///tmp/page.html",
    "contrasts": [
        {"selector": "#note", "text": "mention légale", "fg": "163,170,179", "bg": "255,255,255",
         "ratio": 2.34, "size": 14.0, "bold": False},
        {"selector": "#corps", "text": "texte courant", "fg": "30,30,30", "bg": "255,255,255",
         "ratio": 14.2, "size": 16.0, "bold": False},
    ],
    "images": [
        {"selector": "img#logo", "alt": None, "role": None, "src": "logo.png", "width": 120, "height": 40},
        {"selector": "img#puce", "alt": "", "role": "presentation", "src": "puce.png", "width": 8, "height": 8},
    ],
    "iframes": [{"selector": "iframe#carte", "title": ""}],
    "links": [{"selector": "a#ici", "text": "ici", "aria": None, "title": None, "href": "/x"}],
    "controls": [{"selector": "input#mail", "type": "text", "label": None, "aria": None, "title": None}],
    "headings": [{"level": 1, "text": "Titre"}, {"level": 3, "text": "Sous-titre sauté"}],
    "landmarks": {"main": 0, "nav": 1, "header": 1},
    "hiddenFocusable": [{"selector": "button#abs", "tag": "button"}],
    "jsText": 640,
}

STUB = """#!/bin/sh
cat <<'HTML'
<!doctype html><html lang="fr"><head><title>Page de test</title></head><body>
<h1>Titre</h1><img id="logo" src="logo.png">
<script type="application/json" id="rgaa-browser-report">REPORT_JSON</script>
</body></html>
HTML
"""


class TestRenduStub(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.stub = self.dir / "chrome"
        self.stub.write_text(STUB.replace("REPORT_JSON", json.dumps(REPORT)), encoding="utf-8")
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.previous = os.environ.get("RGAA_CHROME")
        os.environ["RGAA_CHROME"] = str(self.stub)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self.previous is None:
            os.environ.pop("RGAA_CHROME", None)
        else:
            os.environ["RGAA_CHROME"] = self.previous

    def test_detecte_le_binaire(self) -> None:
        self.assertEqual(browser.find_chrome(), str(self.stub))
        self.assertTrue(browser.available()["available"])

    def test_rendu_et_rapport(self) -> None:
        page = self.dir / "page.html"
        page.write_text("<html><body><h1>Brut</h1></body></html>", encoding="utf-8")
        rendered = browser.render(path=page)
        self.assertEqual(rendered.mode, "headless")
        self.assertEqual(rendered.report["title"], "Page de test")
        self.assertIn("rgaa-browser-report", rendered.html)
        self.assertNotIn("rgaa-browser-report", browser.strip_report(rendered.html))

    def test_sonde_apres_le_corps(self) -> None:
        """La sonde doit être lue après le corps, sinon <main> n'existe pas encore."""
        markup = "<html><head><title>x</title></head><body><main>contenu</main></body></html>"
        injected = browser._inject(markup, "file:///tmp/")
        self.assertLess(injected.index("<base"), injected.index("</head>"))
        self.assertGreater(injected.rindex("rgaa-probe"), injected.index("<main>"))
        self.assertIn("DOMContentLoaded", injected)

    def test_constats(self) -> None:
        result = browser_audit.analyse(REPORT, "page.html")
        rules = {row["rule"] for row in result["findings"]}
        self.assertIn("browser-contraste", rules)
        self.assertIn("browser-alt-absente", rules)
        self.assertIn("browser-cadre-sans-titre", rules)
        self.assertIn("browser-champ-sans-etiquette", rules)
        self.assertIn("browser-titre-saute", rules)
        self.assertIn("browser-langue-absente", rules)
        self.assertIn("browser-focus-cache", rules)
        # l'image décorative ne produit rien
        self.assertNotIn("img#puce", {row["selector"] for row in result["findings"]})
        self.assertEqual(result["counts"]["bloquant"], 5)

    def test_rapport_vide(self) -> None:
        result = browser_audit.analyse({}, "page.html")
        self.assertFalse(result["available"])
        self.assertEqual(result["findings"], [])


class TestCouverture(unittest.TestCase):
    def test_total_106(self) -> None:
        data = coverage.matrix()
        self.assertEqual(data["total"], 106)
        self.assertEqual(len(data["criteria"]), 106)
        self.assertEqual(sum(data["counts"].values()), 106)
        self.assertEqual(coverage.check_total(), 106)

    def test_aucun_doublon(self) -> None:
        ids = [row["criterion"] for row in coverage.criteria()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("13.12", ids)

    def test_texte(self) -> None:
        text = coverage.render_text()
        self.assertIn("106 critères", text)
        self.assertIn("3.2", text)


if __name__ == "__main__":
    unittest.main()
