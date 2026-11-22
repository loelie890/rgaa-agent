"""Campagnes : création, modification, suppression, exécution automatique."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from rgaa import campaigns, kernel


class TestCampagnesCrud(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self._saved = campaigns.CAMPAGNE_DIR
        campaigns.CAMPAGNE_DIR = self.base
        self.addCleanup(setattr, campaigns, "CAMPAGNE_DIR", self._saved)

    def test_slug(self) -> None:
        self.assertEqual(campaigns.slugify("Contrôle des pages produits !"), "controle-des-pages-produits")
        self.assertEqual(campaigns.slugify("!!!"), "campagne")

    def test_create_read_update_delete(self) -> None:
        created = campaigns.create("Contrôle produits", "Vérifier les images des pages produits", budget=18)
        self.assertEqual(created["engine"], "auto")
        self.assertEqual(created["budget"], 18)
        self.assertTrue((self.base / "controle-produits" / "campagne.json").is_file())

        updated = campaigns.update("controle-produits", title="Contrôle images", budget=99)
        self.assertEqual(updated["title"], "Contrôle images")
        self.assertEqual(updated["budget"], 60)  # plafonné

        campaigns.delete("controle-produits")
        self.assertFalse((self.base / "controle-produits").exists())

    def test_create_refuses(self) -> None:
        with self.assertRaises(campaigns.CampaignError):
            campaigns.create("ab", "objectif suffisamment long pour passer")
        with self.assertRaises(campaigns.CampaignError):
            campaigns.create("Titre correct", "court")
        campaigns.create("Doublon", "objectif suffisamment long pour passer")
        with self.assertRaises(campaigns.CampaignError):
            campaigns.create("Doublon", "objectif suffisamment long pour passer")

    def test_delete_refuses_cassette(self) -> None:
        target = self.base / "demo"
        target.mkdir()
        (target / "campagne.json").write_text(json.dumps({"slug": "demo", "title": "Démo", "passes": []}), encoding="utf-8")
        with self.assertRaises(campaigns.CampaignError):
            campaigns.delete("demo")

    def test_bad_slug(self) -> None:
        with self.assertRaises(campaigns.CampaignError):
            campaigns.load("../../etc")


class TestEquipeManuelle(unittest.TestCase):
    def test_agents_composes(self) -> None:
        from rgaa.team import run_team

        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            shutil.copytree(Path(kernel.ROOT) / "fixtures" / "site", site)
            result = run_team(
                site,
                write=True,
                agents=[
                    {"name": "agent-images", "role": "media", "pages": "index.html, produits.html"},
                    {"name": "agent-couleurs", "role": "contraste", "pages": "tarifs.html"},
                ],
            )
            names = [entry["agent"] for entry in result["agents"]]
            self.assertEqual(names, ["agent-images", "agent-couleurs"])
            self.assertEqual(result["score"]["percent"], 100.0)
            self.assertGreaterEqual(sum(entry["patches"] for entry in result["agents"]), 15)
            self.assertIn("alt", (site / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
