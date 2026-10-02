"""PlantLens API. Wired: chat + analyze (pipeline: model via HF router -> local KB), saved conversations, journal, events, weather,
uploads, plants, profile, context meter. STUB: /api/compare, /api/plan, /api/why and /api/live return placeholder data."""
from typing import List
import asyncio, json, os, re, sys, threading, uuid
from pathlib import Path
from starlette.concurrency import run_in_threadpool
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))          # makes the repo's src/ package importable
from fastapi import FastAPI, File, Header, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import db

from src.pipeline import Session, DIAGNOSE_COMMANDS, NUM_CTX, SYSTEM as SKILL_TEXT, emit_rag
from src.remote_vlm import MODELS
from src import trace
from src.trace import tok
from src.build_index import build as build_index, load_config

MODEL = MODELS[0]           # served via the Hugging Face router; see src/remote_vlm.py for the fallback order
if not (ROOT / load_config()["index_path"]).exists():
    try:
        build_index(os.environ.get("PLANTLENS_EMBEDDER") or None)       # embedder from kb/config.yaml
    except ImportError:
        print("sentence-transformers not installed; building the index with the offline stand-in embedder (weaker retrieval)")
        build_index("hash")
UPLOADS = Path(__file__).parent / "uploads"
UPLOADS.mkdir(exist_ok=True)

SYSTEM = ("You are PlantLens, a visual plant health assistant. Describe visible symptoms, give 2-4 possible "
          "causes (never an absolute diagnosis), ask focused follow-up questions, and be honest about uncertainty.")

app = FastAPI(title="PlantLens")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
db.init()


def load_trace(tid):
    r = db.rows("SELECT data FROM traces WHERE trace_id=?", (tid,))
    return json.loads(r[0]["data"]) if r else None


trace.LOADER = load_trace


def save_trace(tid):
    """Persist (or update) a trace so past turns can be replayed after a restart."""
    tr = trace.get(tid, create=False) if tid else None
    if not tr: return
    d = tr.to_dict()
    db.run("INSERT INTO traces(trace_id,conversation_id,plant_id,data) VALUES(?,?,?,?) ON CONFLICT(trace_id) DO UPDATE SET "
           "data=excluded.data, updated=CURRENT_TIMESTAMP", (tid, d["meta"].get("conversation_id"), d["meta"].get("plant_id"), json.dumps(d)))


@app.get("/api/traces/{tid}")
def get_trace(tid: str):
    t = trace.get(tid, create=False)
    if not t: raise HTTPException(404, "no such trace")
    return t.to_dict()


@app.get("/api/conversations/{cid}/traces")
def conversation_traces(cid: int):
    """Newest first. Live ones come from memory so spans still running are included."""
    out = []
    for r in db.rows("SELECT trace_id FROM traces WHERE conversation_id=? ORDER BY updated DESC, created DESC LIMIT 20", (cid,)):
        t = trace.get(r["trace_id"], create=False)
        if t: out.append(t.to_dict())
    return out


# ---------- plants / profile / timeline ----------
class PlantIn(BaseModel):
    name: str
    species: str = ""


@app.get("/api/plants")
def plants():
    return db.rows("""SELECT p.*,
      (SELECT image FROM entries WHERE plant_id=p.id AND image IS NOT NULL ORDER BY id DESC LIMIT 1) AS last_image,
      (SELECT text FROM entries WHERE plant_id=p.id AND kind='diagnosis' ORDER BY id DESC LIMIT 1) AS last_diagnosis,
      (SELECT COUNT(*) FROM entries WHERE plant_id=p.id AND kind='diagnosis') AS diagnoses,
      (SELECT COUNT(*) FROM events WHERE plant_id=p.id AND status='planned') AS open_events
      FROM plants p ORDER BY id""")


# ---------- conversation list + titles (messages live in /api/conversations/{id}) ----------
@app.get("/api/conversations")
def all_conversations():
    return db.rows("SELECT id,plant_id,title,updated FROM conversations ORDER BY updated DESC, id DESC")


@app.put("/api/conversations/{cid}/title")
def rename_conversation(cid: int, body: dict):
    db.run("UPDATE conversations SET title=?, renamed=1 WHERE id=?", (body.get("title", "New chat")[:60], cid)); return {"ok": True}


@app.post("/api/conversations/{cid}/title")
async def summarise_title(cid: int):
    """Auto-title: a small local model writes a 3-6 word summary; falls back to the current (first-message) title."""
    r = db.rows("SELECT title,renamed FROM conversations WHERE id=?", (cid,))
    if not r or r[0]["renamed"]: return {"title": r[0]["title"] if r else ""}
    msgs = db.rows("SELECT role,content FROM messages WHERE conversation_id=? AND content!='' ORDER BY id", (cid,))
    convo = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in msgs)[:1500]
    title = r[0]["title"]
    try:
        from src.remote_vlm import RemoteVLM
        prompt = ("Write a 3-6 word title naming the plant and its main problem in this chat. "
                  "Reply with the title only, no quotes or punctuation.\n\n" + convo)
        t = await run_in_threadpool(RemoteVLM().chat, [{"role": "user", "content": prompt}], 20, 0.2)
        t = t.strip().strip('"\'.').split("\n")[0][:60]
        if t: title = t
    except Exception:
        pass                                   # keep the first-message title if the model is unreachable
    db.run("UPDATE conversations SET title=? WHERE id=?", (title, cid))
    return {"title": title}


# ---------- events (progress: past + planned, with results) ----------
@app.get("/api/plants/{pid}/events")
def events(pid: int): return db.rows("SELECT * FROM events WHERE plant_id=? ORDER BY COALESCE(due,created)", (pid,))


# Event actions are recorded on the trace named in the X-Trace-Id header (the chat turn that led to them), if there is one.
@app.post("/api/plants/{pid}/events")
def add_event(pid: int, body: dict, x_trace_id: str = Header("")):
    with trace.use(x_trace_id, create=False), trace.span("event", "Scheduled event: added", title=body.get("title", ""), due=body.get("due")):
        eid = db.run("INSERT INTO events(plant_id,title,due,status,result) VALUES(?,?,?,?,?)",
                     (pid, body.get("title", ""), body.get("due"), body.get("status", "planned"), body.get("result", "")))
    save_trace(x_trace_id)
    return {"id": eid}


@app.put("/api/events/{eid}")
def update_event(eid: int, body: dict, x_trace_id: str = Header("")):
    st = body.get("status", "planned")
    with trace.use(x_trace_id, create=False), trace.span("event", f"Scheduled event: {st}", title=body.get("title"), result=body.get("result", "")):
        db.run("UPDATE events SET title=COALESCE(?,title), due=COALESCE(?,due), status=?, result=?, "
               "done_at=CASE WHEN ?!='planned' THEN CURRENT_TIMESTAMP END WHERE id=?",
               (body.get("title"), body.get("due"), st, body.get("result", ""), st, eid))
    save_trace(x_trace_id)
    return {"ok": True}


@app.delete("/api/events/{eid}")
def del_event(eid: int, x_trace_id: str = Header("")):
    with trace.use(x_trace_id, create=False), trace.span("event", "Scheduled event: deleted", id=eid):
        db.run("DELETE FROM events WHERE id=?", (eid,))
    save_trace(x_trace_id)
    return {"ok": True}


@app.post("/api/plants")
def add_plant(p: PlantIn):
    return {"id": db.run("INSERT INTO plants(name,species) VALUES(?,?)", (p.name, p.species))}


@app.put("/api/plants/{pid}/profile")
def set_profile(pid: int, profile: dict):
    db.run("UPDATE plants SET profile=? WHERE id=?", (json.dumps(profile), pid))
    return {"ok": True}


@app.put("/api/plants/{pid}/status")
def set_status(pid: int, body: dict):
    db.run("UPDATE plants SET status=? WHERE id=?", (body.get("status", "green"), pid))
    return {"ok": True}


@app.get("/api/plants/{pid}/timeline")
def timeline(pid: int):
    return db.rows("SELECT * FROM entries WHERE plant_id=? ORDER BY id DESC", (pid,))


@app.post("/api/plants/{pid}/timeline")
def add_entry(pid: int, body: dict):
    return {"id": db.run("INSERT INTO entries(plant_id,kind,text,image,analysis) VALUES(?,?,?,?,?)",
                         (pid, body.get("kind", "note"), body.get("text", ""), body.get("image"), None))}


# ---------- upload ----------
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "x.jpg").suffix or ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"
    (UPLOADS / name).write_bytes(await file.read())
    return {"image": name, "url": f"/uploads/{name}"}


# ---------- chat + context meter ----------
class ChatIn(BaseModel):
    trace_id: str = ""          # groups this send's /api/chat and /api/analyze calls into one trace
    plant_id: int = 1
    messages: List[dict] = []   # [{role, content, image?}]
    mode: str = "normal"        # normal | rescue | healthy
    conversation_id: int = 0    # 0 = start a new saved conversation
    skill: str = ""             # "diagnose" forces the diagnosis skill (also triggered by typing /diagnose)


MODE_HINT = {
    "rescue": "RESCUE MODE: plant is severely declining. Check water, light, pests, roots, temperature, disease in order.",
    "healthy": "HEALTHY MODE: confirm good signs, flag early warnings, suggest when to re-check.",
}


def build_context(req: ChatIn):
    plant = (db.rows("SELECT * FROM plants WHERE id=?", (req.plant_id,)) or [{}])[0]
    profile = plant.get("profile") or "{}"
    hist = db.rows("SELECT kind,text,created FROM entries WHERE plant_id=? ORDER BY id DESC LIMIT 5", (req.plant_id,))
    refs = []
    parts = {
        "profile": f"Plant: {plant.get('name')} ({plant.get('species')}). Care profile: {profile}",
        "history": "\n".join(f"[{h['created']}] {h['kind']}: {h['text']}" for h in hist),
    }
    conv = "".join(m.get("content", "") for m in req.messages)
    images = sum(1 for m in req.messages if m.get("image"))
    # pre-send estimate with the same keys the pipeline reports after the turn (see Session._record_context)
    segs = [
        {"key": "skill", "label": "Skill instructions", "tokens": tok(SKILL_TEXT) + tok(MODE_HINT.get(req.mode, ""))},
        {"key": "profile", "label": "Plant profile", "tokens": tok(parts["profile"])},
        {"key": "history", "label": "History", "tokens": tok(parts["history"])},
        {"key": "answers", "label": "User answers", "tokens": tok(conv)},
        {"key": "images", "label": "Photo", "tokens": images * 576},
    ]
    return parts, segs, refs


@app.post("/api/context")
def context(req: ChatIn):
    _, segs, _ = build_context(req)
    return {"segments": segs, "used": sum(s["tokens"] for s in segs), "limit": NUM_CTX, "model": MODEL}


# ---------- sessions: one pipeline Session per conversation, shared by /api/analyze and /api/chat ----------
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


def get_session(cid, plant_id):
    """In-memory session for a conversation; restored from the saved state after a restart."""
    with SESSIONS_LOCK:
        key = cid or ("anon", plant_id)
        if key not in SESSIONS:
            st = (db.rows("SELECT state FROM conversations WHERE id=?", (cid,)) or [{}])[0].get("state") if cid else ""
            SESSIONS[key] = Session.from_state(json.loads(st)) if st else Session()
        return SESSIONS[key]


def save_state(cid, s):
    if cid:
        with trace.span("context", "Save conversation state"): _save_state(cid, s)


def _save_state(cid, s):
    db.run("UPDATE conversations SET state=?, updated=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(s.to_state()), cid))


def save_message(cid, role, content="", image=None, analysis=None):
    if not cid: return
    db.run("INSERT INTO messages(conversation_id,role,content,image,analysis) VALUES(?,?,?,?,?)",
           (cid, role, content, image, json.dumps(analysis) if analysis else None))
    db.run("UPDATE conversations SET updated=CURRENT_TIMESTAMP WHERE id=?", (cid,))
    if role == "user" and content.strip():
        db.run("UPDATE conversations SET title=? WHERE id=? AND title='New chat'", (content.strip()[:60], cid))


def ensure_conversation(cid, plant_id, first_text=""):
    if cid and db.rows("SELECT 1 FROM conversations WHERE id=?", (cid,)): return cid
    return db.run("INSERT INTO conversations(plant_id,title) VALUES(?,?)", (plant_id, (first_text or "New chat")[:60]))


STATUS_RED = {"soft_stem_base", "dark_soft_roots", "blackening"}


def analysis_from(obs, kb, regions=()):
    """Structured card from the observation + KB records. Every cause, pest and checklist item comes from a retrieved record."""
    recs = [r["record"] for r in kb["results"]]
    syms = obs.get("symptoms", [])
    healthy = obs.get("health") == "healthy"
    urgency = "green" if healthy else "red" if STATUS_RED & set(syms) else "yellow"   # heuristic, not from the KB
    steps = []
    for r in recs[:3]:
        for x in r["next_actions"] + r["inspect_next"]:
            x = re.sub(r"\s*\((?:Illinois|UMD|UC IPM)\)", "", x)      # sources are listed under "Where this comes from"
            if x not in steps: steps.append(x)
    plant = obs.get("plant") or {}
    unsure = []
    if plant.get("confidence") != "high": unsure.append(f"I'm {plant.get('confidence', 'not')} sure this is {plant.get('name', 'that plant')}; please confirm the plant.")
    if not healthy and not syms: unsure.append("I can't see a clear symptom in this photo. A closer, well-lit photo of the part that looks wrong would help.")
    elif kb["coverage"] != "good" and not healthy: unsure.append("My knowledge base only partly covers this, so treat these as possibilities." if kb["coverage"] == "weak" else "My knowledge base does not cover this case, so I won't list causes.")
    return {
        "stub": False, "urgency": urgency, "plant": plant,
        "symptoms": syms,
        "possibilities": [{"cause": r["cause"], "likelihood": ("high", "medium", "low", "low", "low")[i], "category": r["cause_category"], "record_id": r["record_id"]} for i, r in enumerate(recs[:4])] if not healthy else [],
        "pests": [{"name": r["cause"], "check": (r["inspect_next"] or [q["question"] for q in r["distinguishing_questions"]] or [""])[0]} for r in recs if r["cause_category"] == "pest"],
        "questions": [q["question"] for q in kb["questions"]] if not healthy else [],
        "checklist": (steps[:5] + ["Re-check in 48 hours and send a new photo"]) if steps and not healthy else (["Check again in a week or two"] if healthy else []),
        "regions": list(regions),   # visual symptom map: boxes as 0-1 fractions of the image
        "uncertainty": " ".join(unsure),
        "references": [{"title": r["cause"], "snippet": r["summary"], "url": r["source_url"]} for r in recs],
        "healthy_signs": ["No visible problem in this photo"] if healthy else [],
    }


@app.post("/api/analyze")
async def analyze(body: dict):
    image = body.get("image")
    if not image: raise HTTPException(400, "image required")
    plant_id, cid = body.get("plant_id", 1), body.get("conversation_id", 0)
    tid = body.get("trace_id") or ""
    try:
        with trace.use(tid):
            if trace.current(): trace.current().meta.update(conversation_id=cid, plant_id=plant_id)
            with trace.span("turn", "Photo analysis"):
                s = get_session(cid, plant_id)
                text, skill = body.get("text", ""), body.get("skill", "")
                if text.strip().lower().startswith(DIAGNOSE_COMMANDS): skill, text = "diagnose", ""
                intent = await run_in_threadpool(s.route, text, str(UPLOADS / image), skill)
                if intent not in ("diagnose", "answer"):
                    return {"skipped": True, "intent": intent}       # a plain question: no analysis card
                await run_in_threadpool(s.ensure_observation, str(UPLOADS / image), text)
                kb, regions = await asyncio.gather(run_in_threadpool(s.search), run_in_threadpool(s.locate_regions))
                card = analysis_from(s.observation, kb, regions)
                if kb["results"]: emit_rag(kb, {p["record_id"] for p in card["possibilities"]}, "analysis")
                save_message(cid, "assistant", "", image, card)
                db.run("UPDATE plants SET status=? WHERE id=?", (card["urgency"], plant_id))
                pl = card.get("plant") or {}
                summary = (f"Check-up: {pl.get('name', 'plant')} ({pl.get('confidence', '?')} confidence), status {card['urgency']}. "
                           f"Symptoms: {', '.join(card['symptoms']) or 'none seen'}. "
                           + (f"Possible causes: {', '.join(p['cause'] for p in card['possibilities'])}." if card["possibilities"] else ""))
                db.run("INSERT INTO entries(plant_id,kind,text,image,analysis) VALUES(?,?,?,?,?)", (plant_id, "check-up", summary, image, json.dumps(card)))
                save_state(cid, s)
                return card
    except Exception as e:
        raise HTTPException(502, f"analysis failed: {e}")
    finally:
        save_trace(tid)


@app.post("/api/chat")
async def chat(req: ChatIn):
    parts, segs, _ = build_context(req)
    users = [m for m in req.messages if m["role"] == "user"]
    if not users: raise HTTPException(400, "no user message")
    cid = ensure_conversation(req.conversation_id, req.plant_id, users[0].get("content", ""))
    tid = req.trace_id or trace.new_id()
    tr = trace.get(tid)
    tr.meta.update(conversation_id=cid, plant_id=req.plant_id)
    m = users[-1]
    save_message(cid, "user", m.get("content", ""), m.get("image"))
    extra = "\n".join(x for x in (parts["profile"], parts["history"], MODE_HINT.get(req.mode, "")) if x)

    def run():
        with trace.use(tid), trace.span("turn", "Chat turn", mode=req.mode):
            s = get_session(cid, req.plant_id)
            photo = str(UPLOADS / m["image"]) if m.get("image") else None
            reply = s.turn(m.get("content", ""), photo, extra, req.skill, {"profile": parts["profile"], "history": parts["history"]})
            kb = s.last["kb"] if s.last.get("intent") in ("diagnose", "answer") else {"results": []}
            if s.last.get("stage") == "diagnose" and s.last.get("intent") in ("diagnose", "answer"):   # conclusions go in the journal
                with trace.span("tool", "Write journal entry"):
                    db.run("INSERT INTO entries(plant_id,kind,text,analysis) VALUES(?,?,?,?)",
                           (req.plant_id, "diagnosis", reply, json.dumps({"record_ids": [r["record"]["record_id"] for r in kb["results"]],
                                                                          "coverage": kb.get("coverage")})))
            save_message(cid, "assistant", reply)
            save_state(cid, s)
            return reply

    async def stream():
        loop, q = asyncio.get_running_loop(), asyncio.Queue()
        unsub = tr.subscribe(lambda sp: loop.call_soon_threadsafe(q.put_nowait, sp))   # spans arrive from worker threads
        yield json.dumps({"type": "conversation", "id": cid, "trace_id": tid}) + "\n"
        yield json.dumps({"type": "context", "segments": segs, "used": sum(x["tokens"] for x in segs), "limit": NUM_CTX, "estimate": True}) + "\n"
        job = asyncio.ensure_future(run_in_threadpool(run))
        job.add_done_callback(lambda _: q.put_nowait(None))
        try:
            while True:
                sp = await q.get()
                if sp is None: break
                yield json.dumps({"type": "span", "span": sp}) + "\n"       # live: started + finished snapshots, merged by id in the UI
            try:
                reply = await job
            except Exception as e:
                yield json.dumps({"type": "error", "text": f"Model call failed: {e}"}) + "\n"
                return
            yield json.dumps({"type": "token", "text": reply}) + "\n"
            yield json.dumps({"type": "done", "trace_id": tid}) + "\n"
        finally:
            unsub(); save_trace(tid)
    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ---------- weather impact ----------
@app.post("/api/weather")
async def weather(body: dict):
    from src import weather as W
    pid, place, setting = body.get("plant_id", 1), (body.get("location") or "").strip(), body.get("setting", "")
    if not place: raise HTTPException(400, "location required")
    plant = (db.rows("SELECT * FROM plants WHERE id=?", (pid,)) or [{}])[0]
    try: profile = json.loads(plant.get("profile") or "{}")
    except ValueError: profile = {}
    last = db.rows("SELECT analysis FROM entries WHERE plant_id=? AND kind='check-up' ORDER BY id DESC LIMIT 1", (pid,))
    seen = json.loads(last[0]["analysis"]) if last and last[0]["analysis"] else {}
    ctx = {"name": plant.get("name"), "species": plant.get("species"), "seen_in_last_checkup": (seen.get("plant") or {}).get("name"),
           "symptoms_in_last_checkup": seen.get("symptoms", []), "care_profile": {k: v for k, v in profile.items() if v}}
    try:
        out = await run_in_threadpool(W.check, place, setting, ctx)
    except Exception as e:
        raise HTTPException(502, f"weather check failed: {e}")
    if "error" in out: return out
    profile.setdefault("location", out["place"]); profile["indoor/outdoor"] = profile.get("indoor/outdoor") or setting
    db.run("UPDATE plants SET profile=? WHERE id=?", (json.dumps(profile), pid))
    db.run("INSERT INTO entries(plant_id,kind,text,analysis) VALUES(?,?,?,?)",
           (pid, "weather", f"Weather check for {out['place']} ({out['setting']}):\n" + out["assessment"], json.dumps({"past": out["past"], "future": out["future"], "flags": out["flags"]})))
    return out


# ---------- saved conversations ----------
@app.get("/api/plants/{pid}/conversations")
def conversations(pid: int):
    return db.rows("SELECT c.id, c.title, c.updated, (SELECT count(*) FROM messages m WHERE m.conversation_id=c.id) AS messages "
                   "FROM conversations c WHERE c.plant_id=? ORDER BY c.updated DESC, c.id DESC", (pid,))


@app.post("/api/plants/{pid}/conversations")
def new_conversation(pid: int):
    return {"id": db.run("INSERT INTO conversations(plant_id) VALUES(?)", (pid,))}


@app.get("/api/conversations/{cid}")
def conversation(cid: int):
    msgs = db.rows("SELECT role, content, image, analysis FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
    for m in msgs:
        m["analysis"] = json.loads(m["analysis"]) if m["analysis"] else None
        m["url"] = f"/uploads/{m['image']}" if m["image"] else None
    return {"id": cid, "messages": msgs}


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: int):
    db.run("DELETE FROM messages WHERE conversation_id=?", (cid,)); db.run("DELETE FROM conversations WHERE id=?", (cid,))
    SESSIONS.pop(cid, None)
    return {"ok": True}


@app.post("/api/compare")
def compare(body: dict):
    """STUB: progress comparison between two entry ids / images."""
    return {"stub": True, "trend": "improving", "summary": "Yellowing appears reduced vs. previous photo."}


@app.post("/api/plan")
def plan(body: dict):
    """STUB: recovery plan."""
    return {"stub": True, "today": ["Stop watering"], "next_days": ["Check soil moisture daily"],
            "next_week": ["Upload a new photo to compare"]}


@app.post("/api/why")
def why(body: dict):
    """STUB: explain why a recommendation was made."""
    return {"stub": True, "explanation": "Recommendation is based on yellowing + wet soil in your profile."}


@app.websocket("/api/live")
async def live(ws):
    """STUB (stretch): live video analysis."""
    await ws.accept()
    await ws.send_json({"stub": True, "tip": "Live analysis not implemented yet."})
    await ws.close()
