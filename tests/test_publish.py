"""Publication d'un run : trois fichiers, des durées mesurées, rien d'inventé."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rgaa import kernel
from rgaa.publish import publish


class TestPublish(unittest.TestCase):
    def test_run_publie(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            out = Path(tmp) / "docs" / "runs" / "2026-11-22-vision"
            result = kernel.run_campagne("vision", runs_dir=runs)
            meta = publish(
                result,
                Path(result["run_dir"]),
                out,
                duration_s=1.234,
                vision_model="fake-vl",
            )
            self.assertTrue((out / "journal.jsonl").is_file())
            self.assertTrue((out / "transcript.md").is_file())
            self.assertTrue((out / "meta.json").is_file())
            self.assertEqual(meta["modele_vision"], "fake-vl")
            self.assertEqual(meta["duree_s"], 1.234)
            self.assertEqual(meta["etapes"], sum(p["steps"] for p in result["passes"]))
            self.assertAlmostEqual(meta["par_etape_s"], round(1.234 / meta["etapes"], 3), places=3)
            transcript = (out / "transcript.md").read_text(encoding="utf-8")
            self.assertIn("Conclusion", transcript)
            self.assertIn("deliverables/rapport-vision.html", meta["artefacts"])

    def test_dossier_cree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            result = kernel.run_campagne("audit", runs_dir=runs)
            target = Path(tmp) / "profond" / "ici"
            publish(result, Path(result["run_dir"]), target, duration_s=0.5)
            self.assertTrue((target / "meta.json").is_file())


if __name__ == "__main__":
    unittest.main()
