"""Offline tests for tracing. Run: python -m unittest tests.test_trace -v"""
import threading, unittest
from src import trace


class T(unittest.TestCase):
    def test_spans_are_emitted_when_they_start_and_end(self):
        tr = trace.get("t-live-1"); got = []
        tr.subscribe(lambda s: got.append((s["name"], s["status"])))
        with trace.use("t-live-1"), trace.span("tool", "Step", n=1):
            pass
        self.assertEqual(got, [("Step", "running"), ("Step", "ok")])

    def test_late_subscriber_can_replay_earlier_spans(self):
        with trace.use("t-live-2"), trace.span("tool", "Early"): pass
        tr = trace.get("t-live-2", create=False)
        self.assertEqual([s["name"] for s in tr.to_dict()["spans"]], ["Early"])      # what the chat stream replays on connect

    def test_emit_survives_attrs_changing_while_copying(self):
        tr = trace.get("t-live-3")
        span = {"id": "x", "attrs": {}}
        stop = threading.Event()
        def churn():
            i = 0
            while not stop.is_set(): span["attrs"][f"k{i}"] = i; i += 1; span["attrs"].pop(f"k{i - 1}", None)
        th = threading.Thread(target=churn); th.start()
        try:
            for _ in range(300): tr.emit(span)              # must never raise into the pipeline
        finally:
            stop.set(); th.join()

    def test_span_error_is_recorded(self):
        with trace.use("t-live-4"):
            with self.assertRaises(ValueError), trace.span("tool", "Boom"): raise ValueError("bad")
        s = trace.get("t-live-4", create=False).to_dict()["spans"][0]
        self.assertEqual((s["status"], s["attrs"]["error"]), ("error", "bad"))


if __name__ == "__main__": unittest.main()
