"""Offline tests: plant identification calibration, uncertainty mode and answer grounding. Run: python -m unittest tests.test_identify -v"""
import json, unittest
from unittest import mock
from src import identify as ID
from src.pipeline import plant_line, uncertainty_note, uncertainty_text, numbers_unsupported, search_query, plant_from_text


class FakeVLM:
    """Replies to the three identification prompts in order: A (describe first), B (direct), C (lookalike)."""
    def __init__(self, a, b, c): self.replies = {"features": a, "direct": b, "lookalike": c}

    def chat(self, messages, max_new_tokens=0, temperature=0, label=""):
        text = messages[0]["content"][-1]["text"]
        key = "features" if "features" in text and "candidates" in text and "First list" in text else "lookalike" if "lookalike" in text else "direct"
        return json.dumps(self.replies[key])


def cands(*names): return {"candidates": [{"name": n, "confidence": 80} for n in names]}
C_OK = {"best": "jade plant", "lookalike": "money tree", "feature": "thick oval leaves", "feature_visible": True, "subject_clear": True}


class T(unittest.TestCase):
    def ident(self, a, b, c, others):
        with mock.patch.object(ID, "_cross", return_value=[ID.canon(o) for o in others]):   # the real _cross returns normalised names
            return ID.identify(FakeVLM(a, b, c), "photo.jpg")

    def test_names_fold_to_one_plant(self):
        self.assertEqual(ID.canon("Ficus elastica 'Burgundy'"), "rubber plant")
        self.assertEqual(ID.canon("Sansevieria"), "snake plant")
        self.assertEqual(ID.key(ID.canon("Calathea lancifolia")), ID.key(ID.canon("Calathea ornata")))

    def test_high_only_when_every_family_agrees(self):
        r = self.ident(cands("Jade plant"), cands("jade"), C_OK, ["jade plant", "crassula ovata"])
        self.assertEqual((r["name"], r["confidence"], r["agree"]), ("jade plant", "high", "3/3"))

    def test_other_family_disagreeing_lowers_confidence(self):
        r = self.ident(cands("Pothos"), cands("pothos"), {**C_OK, "best": "pothos"}, ["peace lily", "pothos"])
        self.assertEqual(r["confidence"], "medium")           # 2 of 3 families agree
        r = self.ident(cands("Pothos"), cands("pothos"), {**C_OK, "best": "pothos"}, ["peace lily", "monstera"])
        self.assertEqual((r["confidence"], r["name"]), ("low", None))   # nobody else agrees: no name is asserted

    def test_never_high_without_a_second_opinion(self):
        r = self.ident(cands("Jade plant"), cands("jade"), C_OK, [])
        self.assertNotEqual(r["confidence"], "high")

    def test_unclear_subject_caps_confidence(self):
        r = self.ident(cands("Jade plant"), cands("jade"), {**C_OK, "subject_clear": False}, ["jade", "jade plant"])
        self.assertEqual(r["confidence"], "medium")

    def test_plant_line_is_honest(self):
        self.assertEqual(plant_line({"name": "jade plant", "confidence": "high"}), "jade plant")
        self.assertIn("could also be", plant_line({"name": "pothos", "confidence": "medium", "candidates": ["pothos", "philodendron"], "agree": "2/3"}))
        self.assertEqual(plant_line({"name": "unknown", "confidence": "low", "candidates": ["a", "b", "c"], "agree": "1/3"}), "could not tell which plant this is")

    def test_uncertainty_names_the_most_useful_evidence(self):
        rec = lambda i, cat, insp: {"record_id": f"r{i}", "cause": f"cause{i}", "cause_category": cat, "inspect_next": insp, "distinguishing_questions": []}
        kb = {"results": [{"record": rec(1, "pest", ["Check leaf undersides", "Check stems"])}, {"record": rec(2, "watering", ["Check stems"])}], "coverage": "good"}
        note = uncertainty_note({"plant": {"confidence": "high"}}, kb)
        self.assertIn("causes", note["reasons"])
        self.assertEqual(note["evidence"], "Check leaf undersides")       # the evidence only the first cause would explain
        self.assertIn("Not sure yet", uncertainty_text(note))
        self.assertEqual(uncertainty_text({"reasons": [], "causes": [], "evidence": None, "plant": None}), "")

    def test_numbers_must_come_from_the_references(self):
        recs = [{"summary": "Overwatering causes yellowing", "next_actions": ["Let the soil dry"], "inspect_next": [], "caveats": None}]
        self.assertEqual(numbers_unsupported("Water every 2-4 weeks [rec_000001]", recs), ["2", "4"])
        self.assertEqual(numbers_unsupported("Let the soil dry between waterings [rec_000001]", recs), [])

    def test_search_query_names_plant_and_asks_for_authority_on_safety(self):
        obs = {"plant": {"name": "jade plant", "confidence": "high"}}
        self.assertTrue(search_query("is it safe for my cat?", obs).startswith("jade plant"))
        self.assertIn("ASPCA", search_query("is it safe for my cat?", obs))
        self.assertNotIn("jade", search_query("how much light?", {"plant": {"name": "jade plant", "confidence": "low"}}))

    def test_user_named_plant_is_trusted(self):
        self.assertEqual(plant_from_text("it's a pothos, soil is dry"), "pothos")
        self.assertIsNone(plant_from_text("what's wrong with it"))


if __name__ == "__main__":
    unittest.main()
