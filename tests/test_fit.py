"""Dimensionnement : monotonie et cohérence, sans modèle installé."""

from __future__ import annotations

import unittest

from rgaa import fit


class TestFit(unittest.TestCase):
    def test_hypotheses_affichees(self) -> None:
        data = fit.fit(vram_gb=16, vram_actuelle=4)
        self.assertEqual(data["hypotheses"]["images_par_audit"], 5)
        self.assertEqual(data["hypotheses"]["contexte_jetons"], 8192)
        self.assertIn("quantification", data["hypotheses"])

    def test_monotonie_memoire(self) -> None:
        small = fit.fit(vram_gb=6)
        big = fit.fit(vram_gb=32)
        self.assertGreaterEqual(len(big["tiennent_cible"]), len(small["tiennent_cible"]))
        self.assertIn("qwen2.5vl:3b", small["tiennent_cible"])
        self.assertNotIn("llama3.2-vision:90b", big["tiennent_cible"])

    def test_monotonie_contexte(self) -> None:
        court = fit.fit(vram_gb=32, context=2048)
        long = fit.fit(vram_gb=32, context=32768)
        self.assertGreaterEqual(len(court["tiennent_cible"]), len(long["tiennent_cible"]))
        self.assertGreater(long["models"][0]["cache"], court["models"][0]["cache"])

    def test_un_seul_modele_tient_en_4_go(self) -> None:
        data = fit.fit(vram_gb=16, vram_actuelle=4)
        self.assertEqual(data["tiennent_maintenant"], ["qwen2.5vl:3b"])
        self.assertEqual(data["images_traitees_maintenant"], 5)

    def test_texte(self) -> None:
        self.assertIn("tient", fit.render_text(fit.fit(vram_actuelle=4)))
