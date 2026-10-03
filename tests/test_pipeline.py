"""Offline tests for pipeline logic (no model calls). Run: python -m unittest tests.test_pipeline -v"""
import unittest
from src.pipeline import split_reply, ground_reply, allowed_sections, clean_observation, DIAGNOSE_COMMANDS

REC = lambda i, cause, acts, insp=(): {"record": {"record_id": f"rec_{i:06d}", "cause": cause, "next_actions": list(acts), "inspect_next": list(insp), "source_url": "http://src"}}


class T(unittest.TestCase):
    def test_split_reply(self):
        self.assertEqual(split_reply("Water it when dry."), "Water it when dry.")                       # single short line stays whole
        self.assertEqual(split_reply("Likely dry.\n---\n**What I see:** x"), "Likely dry.\n---\n**What I see:** x")
        self.assertEqual(split_reply("Water it.\n---\nWater it."), "Water it.")                          # repeated summary dropped
        self.assertIn("\n---\n", split_reply("**What I see:** a very long reply. " * 20))                # fallback builds a summary line

    def test_split_reply_keeps_a_natural_multi_sentence_message_whole(self):
        msg = "Those yellow lower leaves look like too much water to me. The soil seems damp in the photo, so I'd hold off watering. Does it stay wet for days?"
        self.assertEqual(split_reply(msg + "\n---\nDetail here."), msg + "\n---\nDetail here.")      # not cut to the first line
        self.assertEqual(split_reply(msg), msg)                                                       # short and plain: no divider added

    def test_ground_reply_replaces_model_steps_and_citations(self):
        kb = {"results": [REC(2, "underwatering or very dry soil", ["Re-check after watering (Illinois)"]), REC(4, "fertilizer or salt buildup", ["Flush the soil"])]}
        out = ground_reply("Dry.\n---\n**Possible causes:**\n1. **Underwatering or very dry soil** [rec_000002] [rec_999999]\n**Next steps:**\n- Water thoroughly now\n", kb)
        self.assertNotIn("Water thoroughly now", out)          # model-written step removed
        self.assertNotIn("rec_999999", out)                     # citation to a record that was not retrieved removed
        self.assertIn("Re-check after watering", out)           # step from the record
        self.assertNotIn("(Illinois)", out)                     # source tags stripped from steps
        self.assertNotIn("Flush the soil", out)                 # cause the model did not name is not used
        self.assertIn("Re-check in 48 hours", out)
        self.assertIn("[rec_000002]", out)

    def test_ground_reply_without_records_is_unchanged(self):
        self.assertEqual(ground_reply("x", {"results": []}), "x")

    def test_allowed_sections(self):
        prob = {"health": "possible_problem", "image_quality": "good", "symptoms": ["yellowing"], "plant": {"confidence": "high"}}
        self.assertIn("NOTHING else", allowed_sections({**prob, "image_quality": "poor"}, "good", False))
        self.assertIn("No causes", allowed_sections({**prob, "health": "healthy"}, "skipped", False))
        self.assertIn("closer", allowed_sections({**prob, "symptoms": []}, "skipped", False))
        self.assertIn("possible causes", allowed_sections(prob, "good", False))
        self.assertIn("won't list causes", allowed_sections(prob, "none", False))
        for a in (False, True):                                 # the app, not the model, writes steps and questions
            self.assertIn("Do not write Next steps", allowed_sections(prob, "good", a))

    def test_clean_observation_drops_unknown_ids_and_maps_plant(self):
        obs, dropped = clean_observation({"plant": {"name": "Pothos", "confidence": "high"}, "plant_part": ["leaf", "petal"],
                                          "symptoms": ["yellowing", "made_up"], "other_visible": ["soil_looks_wet"], "health": "possible_problem"})
        self.assertEqual(sorted(dropped), ["made_up", "petal"])
        self.assertEqual(obs["_retrieval"]["plant"]["id"], "pothos")
        self.assertIn("soil_wet", obs["symptoms"])              # visible clue becomes a searchable symptom

    def test_commands(self):
        self.assertTrue("/diagnose now".startswith(DIAGNOSE_COMMANDS))


if __name__ == "__main__":
    unittest.main()
