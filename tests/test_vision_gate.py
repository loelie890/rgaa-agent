"""Le garde-fou de la vision : pas d'alt anglais, pas d'alt qui décrit des formes."""

from __future__ import annotations

import unittest

from rgaa.vision import clean_description, looks_french, parse_analyse


class TestGardeFou(unittest.TestCase):
    def test_refuse_anglais(self) -> None:
        self.assertEqual(clean_description("The image features a large black circle"), "")
        self.assertFalse(looks_french("a pair of black circles with a blue line"))

    def test_accepte_francais(self) -> None:
        self.assertTrue(looks_french("Trottinette rouge pliée devant la vitrine"))
        self.assertEqual(clean_description("L'image montre une trottinette rouge."), "une trottinette rouge")

    def test_tronque_proprement(self) -> None:
        long = "Un vélo cargo bleu garé devant une boulangerie de quartier avec deux enfants à bord"
        cleaned = clean_description(long, limit=40)
        self.assertLessEqual(len(cleaned), 40)
        self.assertFalse(cleaned.endswith(" "))

    def test_parse_marque_non_utilisable(self) -> None:
        parsed = parse_analyse("DESCRIPTION: The image shows a red scooter\nTEXTE: non\nTYPE: photo")
        self.assertFalse(parsed["usable"])
        self.assertEqual(parsed["description"], "")
        self.assertIn("red scooter", parsed["brut"])


if __name__ == "__main__":
    unittest.main()
