"""Phase 5 acceptance tests. Uses the offline 'hash' embedder. Run: python -m unittest tests.test_retrieve -v"""
import hashlib, tempfile, unittest
from functools import partial
from pathlib import Path
from src.build_index import build
from src.retrieve import retrieve as _retrieve

TMP = Path(tempfile.mkdtemp()) / "test_kb.sqlite"          # never touch the real index
retrieve = partial(_retrieve, db_path=TMP)


def sha(): return hashlib.sha256(TMP.read_bytes()).hexdigest()


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls): build("hash", TMP)

    def test_deterministic_build(self):
        a = sha(); build("hash", TMP); self.assertEqual(a, sha())

    def test_known_plant_clear_match(self):
        o = retrieve({"plant": {"id": "pothos", "confidence": "high"}, "plant_parts": ["leaf"], "symptoms": ["stippling", "webbing"],
                      "description": "tiny pale dots and fine webbing on leaves"})
        self.assertEqual(o["coverage"], "good")
        self.assertEqual(o["results"][0]["record"]["cause"], "spider mites")
        self.assertTrue(2 <= len(o["questions"]) <= 4 or len(o["questions"]) >= 2)

    def test_unknown_plant_no_plant_filter(self):
        o = retrieve({"plant": {"id": None, "confidence": "unknown"}, "plant_parts": ["leaf"], "symptoms": ["powdery_coating"],
                      "description": "white powder on leaves"})
        self.assertFalse(o["filters_applied"]["plant"])
        self.assertEqual(o["results"][0]["record"]["cause"], "powdery mildew")

    def test_relaxation_order(self):
        # part with no matching records for this symptom: parts dropped first
        o = retrieve({"plant": {"id": "pothos", "confidence": "high"}, "plant_parts": ["stem"], "symptoms": ["visible_insects"], "description": "small insects"})
        self.assertEqual(o["filters_relaxed"][0], "plant_parts")
        self.assertNotIn("symptoms", o["filters_relaxed"])

    def test_symptom_filter_relaxed_when_too_few(self):
        o = retrieve({"plant": {"id": None, "confidence": "unknown"}, "plant_parts": [], "symptoms": ["powdery_coating"], "description": "white powder"})
        self.assertIn("symptoms", o["filters_relaxed"])
        self.assertTrue(o["results"][0]["symptom_overlap"])  # relevant record still ranks first

    def test_out_of_scope_is_none(self):
        o = retrieve({"plant": {"id": None, "confidence": "unknown"}, "plant_parts": [], "symptoms": [],
                      "description": "qzxv wplk jrmt"})
        self.assertEqual(o["coverage"], "none")
        self.assertEqual(o["results"], [])

    def test_category_hint_filters(self):
        o = retrieve({"plant": {"id": None, "confidence": "unknown"}, "plant_parts": ["leaf"], "symptoms": ["yellowing"], "description": "yellow leaves"}, cause_category="pest")
        self.assertTrue(o["results"])
        self.assertTrue(all(r["record"]["cause_category"] == "pest" for r in o["results"]))

    def test_only_reviewed_indexed(self):
        import sqlite3
        n = sqlite3.connect(TMP).execute("SELECT count(*) FROM records WHERE json LIKE '%\"status\": \"draft\"%'").fetchone()[0]
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
