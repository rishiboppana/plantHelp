"""Offline tests for the diagnosis step and token streaming. Run: python -m unittest tests.test_diagnose -v"""
import json, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from src.diagnose import assess, diagnosis_text, extract_answers
from src.remote_vlm import RemoteVLM


def rec(i, cause, qs, cat="watering"):
    return {"record_id": f"rec_{i:06d}", "cause": cause, "cause_category": cat, "inspect_next": ["Check the roots"],
            "distinguishing_questions": [{"question": q, "if_yes": "supports this cause", "if_no": "weakens this cause"} for q in qs]}


def kb(*recs):
    return {"results": [{"record": r, "symptom_overlap": ["yellowing"], "keyword_hit": True} for r in recs]}


WET = rec(1, "overwatering", ["Is the soil wet for days?", "Does water drain out?"])
DRY = rec(2, "underwatering", ["Is the soil dry deep down?", "Does it perk up after watering?"])


class T(unittest.TestCase):
    def test_no_answers_is_not_confirmed_and_asks_questions(self):
        dx = assess(kb(WET, DRY), {})
        self.assertNotEqual(dx["status"], "confirmed"); self.assertTrue(dx["confirm"])
        self.assertIn("To confirm", diagnosis_text(dx))

    def test_confirmed_needs_support_margin_and_no_contradiction(self):
        ev = {"Is the soil wet for days?": "yes", "Is the soil dry deep down?": "no", "Does it perk up after watering?": "no"}
        dx = assess(kb(WET, DRY), ev)                       # one support for the leader only
        self.assertEqual((dx["leading"]["cause"], dx["status"]), ("overwatering", "likely"))
        self.assertIn("underwatering", dx["ruled_out"])
        ev["Does water drain out?"] = "yes"                 # second support
        self.assertEqual(assess(kb(WET, DRY), ev)["status"], "confirmed")
        ev["Does water drain out?"] = "no"                  # a contradiction blocks confirmation
        self.assertNotEqual(assess(kb(WET, DRY), ev)["status"], "confirmed")

    def test_answers_flip_the_leader(self):
        ev = {"Is the soil wet for days?": "no", "Does water drain out?": "no", "Is the soil dry deep down?": "yes", "Does it perk up after watering?": "yes"}
        dx = assess(kb(WET, DRY), ev)
        self.assertEqual((dx["leading"]["cause"], dx["status"]), ("underwatering", "confirmed"))

    def test_no_candidates(self):
        self.assertEqual(assess({"results": []}, {})["status"], "none"); self.assertEqual(diagnosis_text(assess({"results": []}, {})), "")

    def test_extract_answers_only_keeps_clear_valid_answers(self):
        class V:
            def __init__(self, r): self.r = r
            def chat(self, *a, **k): return self.r
        qs = ["Is the soil wet?", "Does it drain?"]
        self.assertEqual(extract_answers(V('{"answers":[{"q":1,"a":"Yes"},{"q":2,"a":"maybe"},{"q":9,"a":"no"}]}'), "yes", qs), {"Is the soil wet?": "yes"})
        self.assertEqual(extract_answers(V("garbage"), "hi", qs), {})
        self.assertEqual(extract_answers(V("{}"), "", qs), {})


class SSE(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["stream"] is True
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        for d in ("Likely ", "over", "watering."):
            self.wfile.write(f'data: {json.dumps({"choices": [{"delta": {"content": d}}]})}\n\n'.encode()); self.wfile.flush()
        self.wfile.write(f'data: {json.dumps({"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})}\n\ndata: [DONE]\n\n'.encode())


class Stream(unittest.TestCase):
    def test_stream_chat_yields_deltas_and_usage(self):
        srv = HTTPServer(("127.0.0.1", 0), SSE); threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            v = RemoteVLM(model="m", base_url=f"http://127.0.0.1:{srv.server_port}/v1")        # localhost: no token needed
            got = []
            out = v.stream_chat([{"role": "user", "content": "hi"}], 50, 0.0, "t", on_delta=got.append)
            self.assertEqual(got, ["Likely ", "over", "watering."]); self.assertEqual(out, "Likely overwatering.")
            self.assertEqual(v._tl.usage["total_tokens"], 8)          # usage comes from the final SSE chunk
        finally:
            srv.shutdown()


if __name__ == "__main__": unittest.main()
