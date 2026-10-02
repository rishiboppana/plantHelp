"""Offline tests for the benchmark scoring. Run: python -m unittest tests.test_eval_harness -v"""
import unittest
from src.eval_harness import score, table


class T(unittest.TestCase):
    def test_score(self):
        rows = [({"health": "possible_problem", "symptoms": ["yellowing", "spots"], "plant": "pothos"}, {"health": "possible_problem", "symptoms": ["yellowing", "wilting"], "plant": {"name": "Pothos"}}),
                ({"health": "healthy", "symptoms": []}, {"health": "possible_problem", "symptoms": ["yellowing"]})]
        s = score(rows)
        self.assertEqual((s["n"], s["health_acc"], s["false_alarm_rate"], s["plant_acc"]), (2, 0.5, 1.0, 1.0))
        self.assertAlmostEqual(s["precision"], 1 / 3); self.assertAlmostEqual(s["recall"], 0.5)
        self.assertIn("PlantLens", table({"PlantLens": s}))

    def test_empty_rows_do_not_crash(self):
        self.assertEqual(score([])["f1"], 0.0)


if __name__ == "__main__": unittest.main()
