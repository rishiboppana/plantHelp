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


WX = {"place": "San Jose, California, United States", "past_14_days": {"temp_high_f": 88}, "next_7_days": {"temp_low_f": 41, "temp_high_f": 99},
      "flags": [{"when": "coming", "kind": "cold"}], "daily_coming": [], "alerts": [{"title": "Heat advisory", "url": "https://wx.example/heat", "snippet": "Hot Friday"}]}
SAVED = {"location": "San Jose, California", "setting": "outdoor"}


def run_turn(replies, text="", photo=None, kb=KB, results=RESULTS, skill="", parts=None, weather=WX):
    """One turn with mocked tools. Returns (reply, fake model, kb_search mock, web_search mock); the weather mock is run_turn.wx."""
    vlm = FakeVLM(replies)
    wx = mock.Mock(side_effect=weather) if isinstance(weather, Exception) else mock.Mock(return_value=weather)
    with mock.patch("src.pipeline.retrieve", return_value=kb) as kbs, mock.patch("src.pipeline.web_search", return_value=results) as web, \
         mock.patch("src.pipeline.weather_lookup", wx):
        reply = Session(vlm).turn(text, photo, skill=skill, parts=parts)
    run_turn.wx = wx
    return reply, vlm, kbs, web


class QuestionPath(unittest.TestCase):
    def test_answer_from_a_reference_calls_no_web_search(self):
        reply, vlm, kbs, web = run_turn({"Route message": "QUESTION", "Answer plant question": "Water when the soil is dry [rec_000001].",
                                         "Check answer against references": '{"unsupported": []}'}, "how often do I water a pothos?")
        web.assert_not_called(); kbs.assert_called_once()                 # the KB supplies the references
        self.assertEqual(vlm.labels, ["Route message", "Answer plant question", "Check answer against references"])
        run_turn.wx.assert_not_called()
        self.assertIn("rec_000001", reply)

    def test_uncited_care_answer_is_discarded_and_searched(self):
        _, vlm, _, web = run_turn({"Route message": "QUESTION", "Answer plant question": "Water weekly.",
                                   "Answer with web results": "Per example.org, check the soil first."}, "how often do I water a pothos?")
        web.assert_called_once()
        self.assertIn("Answer with web results", vlm.labels)

    def test_chitchat_calls_no_tool(self):
        reply, vlm, _, web = run_turn({"Route message": "QUESTION", "Answer plant question": "Glad to help!"}, "thanks, that helps")
        web.assert_not_called(); run_turn.wx.assert_not_called()
        self.assertEqual(vlm.labels, ["Route message", "Answer plant question"])

    def test_unknown_answer_triggers_one_web_search_and_a_grounded_answer(self):
        reply, vlm, kbs, web = run_turn({"Route message": "QUESTION", "Answer plant question": "SEARCH: calathea crispy edges",
                                         "Answer with web results": "Dry air is the usual cause, per example.org."}, "why are my calathea edges crispy?")
        web.assert_called_once_with("calathea crispy edges")
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


class WeatherAutoCall(unittest.TestCase):
    Q = "should I bring my plant inside tonight?"

    def test_model_requests_weather_and_the_saved_location_is_used(self):
        reply, vlm, _, web = run_turn({"Route message": "QUESTION", "Answer plant question": "WEATHER:",
                                       "Answer with weather": "Lows near 41F are coming, so it could be too cold outside."}, self.Q, parts=SAVED)
        run_turn.wx.assert_called_once_with("San Jose, California")      # no manual city: the saved location
        web.assert_not_called()                                           # the care-fact guard must not override a weather answer
        self.assertEqual(vlm.labels, ["Route message", "Answer plant question", "Answer with weather"])
        self.assertIn('"temp_low_f": 41', vlm.calls[-1][1][-1]["content"])  # the data reached the model
        self.assertIn("Saved plant location: San Jose, California (outdoor)", vlm.calls[0 + 1][1][1]["content"])
        self.assertIn("**Weather:** Open-Meteo data for San Jose", reply)
        self.assertIn("https://wx.example/heat", reply)

    def test_a_city_named_by_the_user_overrides_the_saved_one(self):
        run_turn({"Route message": "QUESTION", "Answer plant question": "WEATHER: Fresno", "Answer with weather": "Hot in Fresno."},
                 "will it freeze in Fresno this week?", parts=SAVED)
        run_turn.wx.assert_called_once_with("Fresno")

    def test_no_saved_location_means_no_lookup_and_the_model_is_told_to_ask(self):
        reply, vlm, _, _ = run_turn({"Route message": "QUESTION", "Answer plant question": "WEATHER:",
                                     "Answer with weather": "Which city is your plant in?"}, self.Q, parts={})
        run_turn.wx.assert_not_called()
        self.assertIn("No location is saved", vlm.calls[-1][1][-1]["content"])
        self.assertNotIn("Open-Meteo", reply)

    def test_not_requested_means_not_called(self):
        run_turn({"Route message": "QUESTION", "Answer plant question": "Glad to help!"}, "thanks!", parts=SAVED)
        run_turn.wx.assert_not_called()

    def test_failed_lookup_is_reported_to_the_model_and_never_crashes(self):
        for failure in (RuntimeError("network down"), {"error": "Couldn't find a place called 'Xyz'."}):
            reply, vlm, _, _ = run_turn({"Route message": "QUESTION", "Answer plant question": "WEATHER: Xyz",
                                         "Answer with weather": "I couldn't get the weather."}, self.Q, parts=SAVED, weather=failure)
            self.assertIn('"error"', vlm.calls[-1][1][-1]["content"])
            self.assertNotIn("Open-Meteo", reply)

    def test_weather_is_requested_at_most_once(self):
        reply, vlm, _, _ = run_turn({"Route message": "QUESTION", "Answer plant question": "WEATHER:", "Answer with weather": "WEATHER:"}, self.Q, parts=SAVED)
        run_turn.wx.assert_called_once()
        self.assertEqual(vlm.labels.count("Answer with weather"), 1)
        self.assertIn("Which city", reply)

    def test_weather_can_be_followed_by_a_web_search(self):
        _, vlm, _, web = run_turn({"Route message": "QUESTION", "Answer plant question": "WEATHER:", "Answer with weather": "SEARCH: frost tolerance of jade plant",
                                   "Answer with web results": "Per example.org, jade is frost tender."}, self.Q, parts=SAVED)
        run_turn.wx.assert_called_once(); web.assert_called_once()
        self.assertEqual(vlm.labels[-1], "Answer with web results")

    def test_diagnosis_path_does_not_call_weather(self):
        run_turn({"Look at the photo (observation)": json.dumps(OBS), "Verify symptoms (second look)": json.dumps({"yellowing": {"visible": "yes"}}),
                  "Write reply": "Dry."}, "", "x.jpg", parts=SAVED)
        run_turn.wx.assert_not_called()

    def test_prompt_offers_the_weather_tool(self):
        self.assertIn("WEATHER:", pipeline.GENERAL)


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


class WeatherLookup(unittest.TestCase):
    DAY = {"time": "2026-10-01", "temperature_2m_min": 55.0, "temperature_2m_max": 75.0, "precipitation_sum": 0.0,
           "relative_humidity_2m_mean": 50, "uv_index_max": 5, "wind_speed_10m_max": 8}

    def test_parse_weather_request(self):
        p = weather.parse_weather_request
        self.assertEqual(p("WEATHER:"), "")
        self.assertEqual(p("weather: San Jose, CA\nextra"), "San Jose, CA")
        self.assertEqual(p('WEATHER: "Fresno"'), "Fresno")
        self.assertIsNone(p("The weather is nice."))
        self.assertIsNone(p("I will check WEATHER: later"))

    def test_lookup_makes_no_model_call_and_returns_data(self):
        with mock.patch("src.weather.geocode", return_value={"name": "San Jose", "region": "California", "country": "US", "lat": 1, "lon": 2}), \
             mock.patch("src.weather.fetch", return_value=([self.DAY] * 14, [self.DAY] * 7)), mock.patch("src.weather.local_alerts", return_value=[]) as la:
            out = weather.lookup("San Jose")
        self.assertEqual(out["place"], "San Jose, California, US")
        self.assertEqual(out["next_7_days"]["days"], 7); self.assertEqual(len(out["daily_coming"]), 7)
        la.assert_called_once_with("San Jose, California, US")

    def test_lookup_unknown_place_is_an_error_not_an_exception(self):
        with mock.patch("src.weather.geocode", return_value=None):
            self.assertIn("error", weather.lookup("Nowhereville"))


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
