"""Offline tests for progress comparison, plan and why. Run: python -m unittest tests.test_progress -v"""
import unittest
from src.progress import compare_cards, build_plan, explain_card, visual_note

C = lambda sy, u: {"symptoms": sy, "urgency": u}


class T(unittest.TestCase):
    def test_improving_when_symptom_resolved(self):
        r = compare_cards(C(["yellowing", "spots"], "yellow"), C(["yellowing"], "yellow"))
        self.assertEqual(r["trend"], "improving"); self.assertEqual(r["resolved"], ["spots"]); self.assertEqual(r["persisting"], ["yellowing"])

    def test_urgency_drop_beats_symptom_count(self):
        self.assertEqual(compare_cards(C(["wilting"], "red"), C(["wilting", "curling"], "yellow"))["trend"], "improving")

    def test_worsening_and_unchanged_and_changing(self):
        self.assertEqual(compare_cards(C([], "green"), C(["wilting"], "yellow"))["trend"], "worsening")
        self.assertEqual(compare_cards(C(["spots"], "yellow"), C(["spots"], "yellow"))["trend"], "unchanged")
        self.assertEqual(compare_cards(C(["spots"], "yellow"), C(["curling"], "yellow"))["trend"], "changing")

    def test_plan_uses_checklist_and_recheck(self):
        card = {"urgency": "yellow", "possibilities": [1], "checklist": ["Check drainage", "Let soil dry", "Look under leaves", "Re-check in 48 hours and send a new photo"]}
        p = build_plan(card, 2)
        self.assertEqual(p["today"], ["Check drainage", "Let soil dry"]); self.assertIn("Re-check with a new photo in 2 days", p["next_days"])
        self.assertIn("Nothing urgent", build_plan({"urgency": "green"})["today"][0])

    def test_explain_links_symptoms_cause_and_profile(self):
        card = {"symptoms": ["yellowing"], "possibilities": [{"cause": "Overwatering", "likelihood": "high"}], "references": [{"title": "Overwatering", "snippet": "Soggy soil.", "url": "http://x"}]}
        e = explain_card(card, {"light": "low"})
        self.assertIn("yellowing", e["explanation"]); self.assertIn("light: low", e["explanation"]); self.assertEqual(e["items"][0]["source"], "http://x")
        self.assertEqual(explain_card(card, None, "pests")["items"], [])

    def test_visual_note_failure_is_none(self):
        class Bad:
            def chat(self, *a, **k): raise RuntimeError("down")
        self.assertIsNone(visual_note(Bad(), "a.jpg", "b.jpg"))


if __name__ == "__main__": unittest.main()
