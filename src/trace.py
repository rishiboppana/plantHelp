"""Per-turn tracing for PlantLens. One trace = everything that happens for one user send (chat + photo analysis + any
scheduled-event actions that follow). A span is one step: model call, retrieval, tool, context update, event action.

    with trace.use(trace_id), trace.span("model", "Write reply", max_tokens=1000) as a:
        ...                      # a is the span's attrs dict: a["prompt_tokens"] = 123
Without an active trace every call is a no-op, so the pipeline still runs from the CLI.
"""
import contextvars, json, threading, time, uuid
from contextlib import contextmanager

_trace = contextvars.ContextVar("plantlens_trace", default=None)
_parent = contextvars.ContextVar("plantlens_span_parent", default=None)
REG, REG_LOCK, MAX_LIVE = {}, threading.Lock(), 60
LOADER = None                      # set by the backend: tid -> saved dict | None (lets events append to an older trace)


def tok(s):
    """Rough token estimate (about 4 characters per token) used when the provider reports no usage."""
    if not isinstance(s, str): s = json.dumps(s, default=str)
    return max(1, len(s) // 4) if s else 0


class Trace:
    def __init__(self, tid, started=None):
        self.id, self.started = tid, started or time.time()
        self.spans, self.meta, self.subs, self.lock = [], {}, [], threading.Lock()

    def ms(self): return round((time.time() - self.started) * 1000)

    def emit(self, span):
        snap = json.loads(json.dumps(span, default=str))      # copy now: attrs keep changing while the span runs
        for f in list(self.subs):
            try: f(snap)
            except Exception: pass

    def subscribe(self, f):
        self.subs.append(f)
        return lambda: self.subs.remove(f) if f in self.subs else None

    def to_dict(self):
        with self.lock: return {"id": self.id, "started": self.started, "meta": self.meta, "spans": json.loads(json.dumps(self.spans, default=str))}

    @classmethod
    def from_dict(cls, d):
        t = cls(d["id"], d.get("started")); t.spans, t.meta = d.get("spans", []), d.get("meta", {})
        return t


def get(tid, create=True):
    if not tid: return None
    with REG_LOCK:
        if tid in REG: return REG[tid]
        saved = LOADER(tid) if LOADER else None
        if saved: REG[tid] = Trace.from_dict(saved)
        elif create: REG[tid] = Trace(tid)
        else: return None
        while len(REG) > MAX_LIVE: REG.pop(next(iter(REG)))
        return REG[tid]


def new_id(): return uuid.uuid4().hex[:12]


def current(): return _trace.get()


@contextmanager
def use(tid, create=True):
    """Make `tid` the active trace for this thread/task (contextvars are copied into worker threads)."""
    t = _trace.set(get(tid, create))
    try: yield
    finally: _trace.reset(t)


@contextmanager
def span(kind, name, **attrs):
    tr = _trace.get()
    if not tr:
        yield dict(attrs); return
    s = {"id": uuid.uuid4().hex[:8], "parent": _parent.get(), "kind": kind, "name": name, "start_ms": tr.ms(),
         "dur_ms": None, "status": "running", "attrs": dict(attrs)}
    with tr.lock: tr.spans.append(s)
    tr.emit(s)
    p, t0 = _parent.set(s["id"]), time.perf_counter()
    try:
        yield s["attrs"]
        s["status"] = "ok"
    except BaseException as e:
        s["status"], s["attrs"]["error"] = "error", str(e)[:300]
        raise
    finally:
        _parent.reset(p)
        s["dur_ms"] = round((time.perf_counter() - t0) * 1000)
        tr.emit(s)


def event(kind, name, **attrs):
    """A zero-length span: something that happened at one instant."""
    with span(kind, name, **attrs): pass


def context(segments, limit, used, **extra):
    event("context", "Context window", segments=segments, limit=limit, used=used, **extra)
