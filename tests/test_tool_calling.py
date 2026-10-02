"""Tool-calling tests: the right tool runs for the right message, and no tool runs when it is not needed.
Offline: the model is a scripted fake (by call label) and the tools (KB search, web search, weather) are mocks that record their calls.
Run: python -m unittest tests.test_tool_calling -v"""
import json, unittest
from unittest import mock
from src import pipeline, weather
from src.pipeline import Session
from src import websearch

RESULTS = [{"title": "Calathea care", "url": "https://example.org/calathea", "snippet": "Crispy edges come from dry air."},
           {"title": "Prayer plants", "url": "https://example.org/prayer", "snippet": "Use filtered water."}]
REC = {"record_id": "rec_000001", "cause": "underwatering or very dry soil", "cause_category": "watering", "summary": "Dry soil browns leaf tips.",
       "distinguishing_questions": [{"question": "Is the soil dry?"}], "next_actions": ["Water thoroughly"], "inspect_next": ["Check the roots"],
       "caveats": [], "source_url": "http://src"}
KB = {"results": [{"record": REC, "score": 1.0, "cosine": 0.5, "keyword_hit": True, "symptom_overlap": 1}], "coverage": "good",
      "filters_applied": {}, "filters_relaxed": [], "questions": [{"question": "Is the soil dry?"}],
      "debug": {"filtered_ids": ["rec_000001"], "keyword_ids": ["rec_000001"], "vector_ids": ["rec_000001"]}}
OBS = {"image_quality": "good", "plant": {"name": "pothos", "confidence": "high"}, "plant_part": ["leaf"], "health": "possible_problem",
       "symptoms": ["yellowing"], "location_patterns": [], "other_visible": []}


class FakeVLM:
    """replies: {label: str | [str, ...] | callable(messages)}; records every call as (label, messages)."""
    def __init__(self, replies):
        self.replies, self.calls, self.on_usage, self.last_usage = replies, [], None, None

    def chat(self, messages, max_new_tokens=700, temperature=0.3, label="Model call"):
        self.calls.append((label, messages))
        r = self.replies.get(label, "")
        if isinstance(r, list): r = r.pop(0) if len(r) > 1 else r[0]
        return r(messages) if callable(r) else r

    @property
    def labels(self): return [l for l, _ in self.calls]


def run_turn(replies, text="", photo=None, kb=KB, results=RESULTS, skill=""):
    """One turn with mocked tools. Returns (reply, fake model, kb_search mock, web_search mock)."""
    vlm = FakeVLM(replies)
    with mock.patch("src.pipeline.retrieve", return_value=kb) as kbs, mock.patch("src.pipeline.web_search", return_value=results) as web:
        reply = Session(vlm).turn(text, photo, skill=skill)
    return reply, vlm, kbs, web


class QuestionPath(unittest.TestCase):
    def test_confident_answer_calls_no_tool(self):
        reply, vlm, kbs, web = run_turn({"Route message": "QUESTION", "Answer plant question": "Water when the top inch is dry."}, "how often do I water a pothos?")
        web.assert_not_called(); kbs.assert_not_called()
        self.assertEqual(vlm.labels, ["Route message", "Answer plant question"])
        self.assertEqual(reply, "Water when the top inch is dry.")

    def test_unknown_answer_triggers_one_web_search_and_a_grounded_answer(self):
        reply, vlm, kbs, web = run_turn({"Route message": "QUESTION", "Answer plant question": "SEARCH: calathea crispy edges",
                                         "Answer with web results": "Dry air is the usual cause, per example.org."}, "why are my calathea edges crispy?")
        web.assert_called_once_with("calathea crispy edges")
        kbs.assert_not_called()                                           # the KB is for diagnosis, not for plain questions
        self.assertEqual(vlm.labels, ["Route message", "Answer plant question", "Answer with web results"])
        second = vlm.calls[-1][1][-1]["content"]
        self.assertIn("https://example.org/calathea", second)             # the results reached the model
        self.assertIn("Never output SEARCH: again", second)
        self.assertIn("**Sources:** https://example.org/calathea", reply)
        self.assertTrue(reply.startswith("Dry air is the usual cause"))

    def test_search_is_limited_to_one_per_turn(self):
        reply, vlm, _, web = run_turn({"Route message": "QUESTION", "Answer plant question": "SEARCH: a",
                                       "Answer with web results": "SEARCH: b"}, "rare question")
        web.assert_called_once()
        self.assertNotIn("SEARCH:", reply)
        self.assertEqual(vlm.labels.count("Answer with web results"), 1)

    def test_failed_search_still_answers_and_says_so(self):
        reply, vlm, _, web = run_turn({"Route message": "QUESTION", "Answer plant question": "SEARCH: x",
                                       "Answer with web results": "I could not confirm that."}, "obscure?", results=[])
        self.assertIn("no results", vlm.calls[-1][1][-1]["content"])
        self.assertNotIn("Sources", reply)

    def test_general_prompt_offers_the_search_tool(self):
        self.assertIn("SEARCH:", pipeline.GENERAL)


class Routing(unittest.TestCase):
    def test_offtopic_calls_no_tool_and_no_answer_model(self):
        reply, vlm, kbs, web = run_turn({"Route message": "OFFTOPIC"}, "who won the game?")
        web.assert_not_called(); kbs.assert_not_called()
        self.assertEqual(vlm.labels, ["Route message"])
        self.assertIn("only help with plants", reply)

    def test_slash_command_skips_the_router(self):
        _, vlm, kbs, _ = run_turn({"Look at the photo (observation)": json.dumps(OBS), "Write reply": "Dry soil.\n---\nunderwatering or very dry soil"},
                                  "/diagnose", "x.jpg")
        self.assertNotIn("Route message", vlm.labels)
        kbs.assert_called_once()

    def test_photo_without_text_goes_to_diagnosis_without_the_router(self):
        _, vlm, _, _ = run_turn({"Look at the photo (observation)": json.dumps({**OBS, "health": "healthy", "symptoms": []})}, "", "x.jpg")
        self.assertNotIn("Route message", vlm.labels)


class DiagnosisPath(unittest.TestCase):
    VERIFY = json.dumps({"yellowing": {"visible": "yes", "evidence": "lower leaf"}})

    def test_problem_photo_searches_the_kb_and_never_the_web(self):
        reply, vlm, kbs, web = run_turn({"Look at the photo (observation)": json.dumps(OBS), "Verify symptoms (second look)": self.VERIFY,
                                         "Write reply": "Likely dry soil.\n---\n**Possible causes:** underwatering or very dry soil"}, "", "x.jpg")
        kbs.assert_called_once(); web.assert_not_called()
        self.assertEqual(kbs.call_args[0][0]["symptoms"], ["yellowing"])   # the search got the observed symptoms
        self.assertIn("[rec_000001]", reply)                                # reply was grounded in the record
        self.assertIn("Water thoroughly", reply)                            # next steps come from the KB, not the model
        self.assertNotIn("SEARCH:", vlm.calls[-1][1][0]["content"])         # the search instruction is not in the diagnosis prompt

    def test_healthy_photo_skips_kb_and_web(self):
        reply, vlm, kbs, web = run_turn({"Look at the photo (observation)": json.dumps({**OBS, "health": "healthy", "symptoms": []}),
                                         "Write reply": "Looks healthy."}, "", "x.jpg")
        kbs.assert_not_called(); web.assert_not_called()
        self.assertNotIn("Verify symptoms (second look)", vlm.labels)       # nothing to verify on a healthy plant

    def test_poor_photo_skips_everything_but_the_look(self):
        _, vlm, kbs, web = run_turn({"Look at the photo (observation)": json.dumps({**OBS, "image_quality": "poor", "symptoms": []}),
                                     "Write reply": "Please send a clearer photo."}, "", "x.jpg")
        kbs.assert_not_called(); web.assert_not_called()

    def test_hallucinated_ids_trigger_a_retry_with_the_vocabulary_check(self):
        bad = json.dumps({**OBS, "symptoms": ["yellowing", "made_up"]})
        _, vlm, _, _ = run_turn({"Look at the photo (observation)": [bad, json.dumps(OBS)], "Verify symptoms (second look)": self.VERIFY,
                                 "Write reply": "Dry."}, "", "x.jpg")
        self.assertEqual(vlm.labels.count("Look at the photo (observation)"), 2)
        self.assertIn("Invalid ids", vlm.calls[1][1][-1]["content"][-1]["text"])


class SearchHelpers(unittest.TestCase):
    def test_parse_search_request(self):
        p = websearch.parse_search_request
        self.assertEqual(p('SEARCH: "calathea ornata care"'), "calathea ornata care")
        self.assertEqual(p("search: pothos toxicity\nextra"), "pothos toxicity")
        self.assertIsNone(p("Water weekly."))
        self.assertIsNone(p("I would SEARCH: later"))                       # only a reply that starts with it counts
        self.assertIsNone(p("SEARCH:"))

    def test_backend_order_prefers_tavily_then_falls_through(self):
        with mock.patch("src.websearch.tavily_key", return_value="k"), mock.patch("src.websearch._tavily", side_effect=RuntimeError("down")), \
             mock.patch("src.websearch._duckduckgo", return_value=[]), mock.patch("src.websearch._wikipedia", return_value=[{"title": "t", "url": "u", "snippet": "s"}]) as wiki:
            self.assertEqual(websearch.web_search("q")[0]["url"], "u")
            wiki.assert_called_once()

    def test_no_key_never_calls_tavily(self):
        with mock.patch("src.websearch.tavily_key", return_value=""), mock.patch("src.websearch._tavily") as tv, \
             mock.patch("src.websearch._duckduckgo", return_value=[{"title": "t", "url": "u", "snippet": "s"}]):
            websearch.web_search("q")
            tv.assert_not_called()


class WeatherTool(unittest.TestCase):
    DAY = {"time": "2026-10-01", "temperature_2m_min": 55.0, "temperature_2m_max": 75.0, "precipitation_sum": 0.0,
           "relative_humidity_2m_mean": 50, "uv_index_max": 5, "wind_speed_10m_max": 8}

    def run_check(self, alerts):
        vlm = FakeVLM({"Model call": "Fine.\n---\n**Past two weeks** ok"})
        with mock.patch("src.weather.geocode", return_value={"name": "San Jose", "region": "California", "country": "US", "lat": 1, "lon": 2}), \
             mock.patch("src.weather.fetch", return_value=([self.DAY] * 14, [self.DAY] * 7)), mock.patch("src.weather.weather_records", return_value=[]), \
             mock.patch("src.weather.local_alerts", return_value=alerts) as la:
            out = weather.check("San Jose", "outdoor", {}, vlm)
        return out, vlm, la

    def test_weather_check_calls_the_search_tool_once_and_passes_results_to_the_model(self):
        out, vlm, la = self.run_check([{"title": "Frost warning", "url": "https://wx.example/frost", "snippet": "Frost Friday"}])
        la.assert_called_once_with("San Jose, California, US")
        self.assertIn("https://wx.example/frost", vlm.calls[0][1][-1]["content"])
        self.assertEqual(out["alerts"][0]["title"], "Frost warning")

    def test_no_alerts_leaves_the_prompt_unchanged(self):
        out, vlm, _ = self.run_check([])
        self.assertNotIn("web_search_local_news", vlm.calls[0][1][-1]["content"])

    def test_local_alerts_is_skipped_without_a_key_and_never_raises(self):
        with mock.patch("src.websearch.tavily_key", return_value=""), mock.patch("src.websearch._tavily") as tv:
            self.assertEqual(weather.local_alerts("X"), [])
            tv.assert_not_called()
        with mock.patch("src.websearch.tavily_key", return_value="k"), mock.patch("src.websearch._tavily", side_effect=OSError("net")):
            self.assertEqual(weather.local_alerts("X"), [])


if __name__ == "__main__":
    unittest.main()
