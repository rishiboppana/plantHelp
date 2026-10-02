"""PlantLens pipeline: photo -> observation JSON (model) -> retrieve (local KB) -> reply (model, records only).
CLI:  python -m src.pipeline --photo test_photos/x.jpg [--text "..."]   (then type follow-up answers; empty line quits)
"""
import argparse, json, os, re, threading
from pathlib import Path
import yaml
from src.remote_vlm import RemoteVLM
from src.retrieve import retrieve
from src import trace
from src.trace import span, tok
from src.validate.validate import KB

SKILL = KB.parent / "plantlens"
NUM_CTX = int(os.environ.get("PLANTLENS_CTX", 16384))   # context budget shown in the meter (set to the served model's real window)
OTHER_TO_SYMPTOM = {"soil_looks_wet": "soil_wet", "soil_looks_dry": "soil_dry", "soil_crusted": "soil_crust",
                    "webbing": "webbing", "insects_visible": "visible_insects"}


def _vocab():
    s = yaml.safe_load((KB / "vocab" / "symptoms.yaml").read_text())
    pl = yaml.safe_load((KB / "vocab" / "plants.yaml").read_text())["plants"]
    parts = {p["id"] for p in yaml.safe_load((KB / "vocab" / "plant_parts.yaml").read_text())["plant_parts"]}
    names = {n.lower(): p["id"] for p in pl for n in p["names"] + p.get("aliases", [])}
    return {x["id"] for x in s["symptoms"]}, {x["id"] for x in s["location_patterns"]}, parts, names, {x["id"]: x["label"] for x in s["symptoms"]}


SYMPTOMS, LOCATIONS, PARTS, PLANT_NAMES, SYMPTOM_LABELS = _vocab()
SYSTEM = (SKILL / "SKILL.md").read_text() + "\n\n" + (SKILL / "references" / "symptoms.md").read_text()


def _iou(r, b):
    """Overlap of region r ({x,y,w,h}) with box b (x,y,w,h), as intersection over union."""
    ix = max(0.0, min(r["x"] + r["w"], b[0] + b[2]) - max(r["x"], b[0]))
    iy = max(0.0, min(r["y"] + r["h"], b[1] + b[3]) - max(r["y"], b[1]))
    inter = ix * iy
    return inter / (r["w"] * r["h"] + b[2] * b[3] - inter)


DIAGNOSE_COMMANDS = ("/diagnose", "/plantlens", "/check")

ROUTER = """You route messages in a plant-care chat. Reply with ONE word:
DIAGNOSE - the user wants to find out what is wrong, or whether the plant is okay, or asks to check/diagnose a problem.
ANSWER - the message gives information in reply to the assistant's questions, such as 'yes', 'it's a cactus' or 'the soil is dry' (only possible if awaiting_answers is yes). A message that ASKS a question is never ANSWER.
QUESTION - any other plant question: care, how much to water, light, repotting, identification, safety, what to do about one leaf.
OFFTOPIC - not about plants.
If has_photo is yes and the message is a greeting, a statement, or asks about health, choose DIAGNOSE. With a photo, choose QUESTION only when the user asks something specific that is not about what is wrong (for example how much to water, or what plant this is)."""

GENERAL = """You are PlantLens, a friendly plant helper. Answer the user's question directly in plain language, in 2 to 5 short sentences.
Do not use headings or sections. Do not describe the photo again, list possible causes, or give a checklist unless the user asked for a diagnosis.
Use the context about the user's plant when it helps (name the plant if known, and say so if you are unsure which plant it is).
If the answer depends on things you cannot see (pot size, light, season, soil), say briefly what it depends on, and give a rough starting guide rather than a rigid schedule.
If the user describes a problem, suggest sending a photo or typing /diagnose so you can check it properly.
Never recommend specific pesticide products or doses. For pets or children eating a plant, suggest a vet or poison-control line.
If it is not about plants, say you only help with plants.
Start with ONE plain sentence that directly answers the question, alone on the first line. Only if extra detail is genuinely useful, add a line containing only --- and then the detail; otherwise stop after the first sentence."""


FORMAT = ("FORMAT: write ONE plain sentence (under 25 words) giving the bottom line, alone on the first line. Then a line containing only --- . "
          "Then the sections. The user sees only the first line unless they tap to expand.")


def split_reply(reply):
    """Normalise a reply to 'one-line summary\\n---\\ndetail' (summary only when there is no detail)."""
    reply = reply.strip()
    m = re.split(r"\n\s*-{3,}\s*\n", reply, maxsplit=1)
    if len(m) == 2 and m[0].strip():
        head, detail = m[0].strip(), m[1].strip()
        lines = head.splitlines()
        summary, detail = lines[0].strip(), ("\n".join(lines[1:]).strip() + "\n" + detail).strip()
        norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
        if norm(detail).startswith(norm(summary)[:60]) and len(detail) < len(summary) * 1.5:
            detail = ""                                    # the model just repeated the summary
        return f"{summary}\n---\n{detail}" if detail else summary
    plain = re.sub(r"[*_#>`]", "", reply)
    first = re.split(r"(?<=[.!?])\s", plain.strip().splitlines()[0] if plain.strip() else "", 1)[0][:200] if plain.strip() else ""
    if "\n" not in reply and len(reply) <= 220:
        return reply                                   # already a single short line
    return f"{first}\n---\n{reply}"


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def clean_observation(raw):
    """Drop ids that are not in the vocabulary; return (observation, dropped)."""
    dropped = []

    def keep(vals, allowed, label):
        ok = [v for v in vals or [] if v in allowed]
        dropped.extend(v for v in vals or [] if v not in allowed)
        return ok

    sym = keep(raw.get("symptoms"), SYMPTOMS, "symptoms")
    loc = keep(raw.get("location_patterns"), LOCATIONS, "location_patterns")
    parts = keep(raw.get("plant_part"), PARTS, "plant_part")
    for o in raw.get("other_visible") or []:
        if o in OTHER_TO_SYMPTOM and OTHER_TO_SYMPTOM[o] not in sym: sym.append(OTHER_TO_SYMPTOM[o])
    plant = raw.get("plant") or {}
    pid = PLANT_NAMES.get(str(plant.get("name", "")).lower())
    obs = dict(raw, symptoms=sym, location_patterns=loc, plant_part=parts)
    obs["_retrieval"] = {"plant": {"id": pid, "confidence": plant.get("confidence") if pid else "unknown"},
                         "plant_parts": parts, "symptoms": sym, "location_patterns": loc,
                         "description": " ".join(str(x) for x in [raw.get("other_visible") or "", " ".join(sym)])}
    return obs, dropped


def allowed_sections(obs, coverage, answered):
    """Apply the 'First decide what to write' table from SKILL.md in code, with the app's change: questions are optional,
    so provisional causes are shown straight away and answers only refine them."""
    if obs.get("image_quality") == "poor":
        return "a short request for a better photo and NOTHING else"
    if obs.get("health") == "healthy":
        return "1 What I see, 2 Plant, 3 Overall, plus one line on what to watch for. No causes, no questions, no checklist"
    if not obs.get("symptoms"):
        return ("1 What I see, 2 Plant, 3 Overall (say Not sure), then ask for a closer, well-lit photo of the part that looks wrong. "
                "No causes, no checklist. Do not write any questions; the app adds them")
    unsure = (obs.get("plant") or {}).get("confidence") != "high" and not answered
    plant = "2 Plant (say how sure you are; the user may confirm it if they like)" if unsure else "2 Plant"
    if coverage == "none":
        return (f"1 What I see, {plant}, 3 Overall, plus the sentence 'My knowledge base does not cover this case, so I won't list causes.' "
                "No causes; the only checklist is: look closely at the undersides of leaves and re-check in 48 hours. "
                "Do not write any questions; the app adds them")
    if not answered:
        return (f"1 What I see, {plant}, 3 Overall, 5 Possible causes (2-4, say they are provisional until the user shares more). "
                "Do not write Next steps or any questions; the app adds them from the records")
    return ("1 What I see, 2 Plant, 3 Overall, 5 Possible causes (2-4, each from the records). "
            "Do not write Next steps or any questions; the app adds them from the records")


def rag_chunks(kb, cited=(), fallback=()):
    """Evidence rows for the UI: each retrieved record with its scores, where it ranked, and whether the answer used it.
    sent = it was in the prompt; cited = the reply cites it or its next steps came from it; fallback = added only because
    no cause matched the reply text (the top 3 are used then)."""
    dbg = kb.get("debug") or {}
    kw, vec = dbg.get("keyword_ids", []), dbg.get("vector_ids", [])
    rows = []
    for i, r in enumerate(kb.get("results", []), 1):
        rec = r["record"]; rid = rec["record_id"]
        rows.append({"rank": i, "record_id": rid, "cause": rec["cause"], "category": rec["cause_category"], "score": r["score"],
                     "cosine": r["cosine"], "keyword_hit": r["keyword_hit"], "kw_rank": kw.index(rid) + 1 if rid in kw else None,
                     "vec_rank": vec.index(rid) + 1 if rid in vec else None, "symptom_overlap": r["symptom_overlap"],
                     "source_url": rec["source_url"], "summary": rec["summary"][:240], "sent": True,
                     "cited": rid in cited, "fallback": rid in fallback})
    return rows


def emit_rag(kb, cited, source, fallback=()):
    trace.event("rag", "RAG evidence" if source == "reply" else "RAG evidence (photo analysis)", source=source,
                coverage=kb.get("coverage"), filters_applied=kb.get("filters_applied"), filters_relaxed=kb.get("filters_relaxed"),
                chunks=rag_chunks(kb, set(cited), set(fallback)))


def ground_reply(reply, kb, report=None):
    """Make a diagnosis reply traceable: next steps and sources are written by code from the retrieved records only,
    any step the model wrote on its own is removed, and citations to records that were not retrieved are dropped."""
    recs = [r["record"] for r in kb.get("results", [])]
    if not recs: return reply
    ids = {r["record_id"] for r in recs}
    reply = re.sub(r"\[(rec_\d+)\]", lambda m: m.group(0) if m.group(1) in ids else "", reply)
    reply = re.sub(r"\n?\*\*Next steps:?\*\*:?.*?(?=\n\*\*[A-Z]|\Z)", "", reply, flags=re.S)       # drop model-written steps
    low = reply.lower()
    matched = [r for r in recs if r["cause"].lower().split(" (")[0] in low or r["cause"].lower().split(" or ")[0] in low]
    used = matched or recs[:3]
    if report is not None: report.update(used=[r["record_id"] for r in used], fallback=not matched)
    steps = []
    for r in used:
        for x in r["next_actions"] + r["inspect_next"]:
            if x not in steps: steps.append(x)
    steps = [re.sub(r"\s*\((?:Illinois|UMD|UC IPM)\)", "", x) for x in steps][:5] + ["Re-check in 48 hours, and send a new photo if anything changes"]
    out = reply.rstrip() + "\n**Next steps** (from the knowledge base):\n" + "\n".join(f"- {x}" for x in steps)
    out += "\n**Based on:** " + "; ".join(f"{r['cause']} [{r['record_id']}]" for r in used)
    out += "\n**Sources:** " + ", ".join(dict.fromkeys(r["source_url"] for r in used))
    return out


class Session:
    def __init__(self, vlm=None):
        self.vlm = vlm or RemoteVLM()
        self.history = []          # user/assistant messages for the reply call
        self.observation = None
        self.last = {}
        self.turns = 0             # every user message handled (used by the backend to detect lost sessions)
        self.diag_turns = 0        # turns that ran the diagnosis skill
        self.photo = None
        self.regions = None        # cached symptom map; None = not computed yet
        self.qa_history = []       # plain Q&A turns outside the diagnosis skill
        self.route_cache = {}
        self.lock = threading.RLock()   # analyze and chat may arrive together; observe only once

    def _observe(self, photo, text):
        ask = ("Output ONLY the observation JSON described in the skill. Use only symptom, location and plant_part ids from the "
               "symptom reference. Describe what is visible; do not guess.")
        content = ([{"type": "image_path", "path": photo}] if photo else []) + [{"type": "text", "text": (text or "") + "\n\n" + ask}]
        raw = None
        for _ in range(2):
            reply = self.vlm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}], 500, 0.0, "Look at the photo (observation)")
            try:
                raw = parse_json(reply)
            except ValueError:
                raw = None
            if raw:
                with span("tool", "Check ids against vocabulary") as a:
                    obs, dropped = clean_observation(raw)
                    a["dropped_ids"] = dropped
                if not dropped: return self._verify(photo, obs), dropped
                content = content + [{"type": "text", "text": f"Invalid ids: {dropped}. Use only ids from the symptom reference. Output the JSON again."}]
        return (clean_observation(raw) if raw else ({"_retrieval": {"plant": {"id": None, "confidence": "unknown"}, "plant_parts": [], "symptoms": [], "location_patterns": [], "description": ""}, "health": "unclear", "image_quality": "poor"}, ["unparseable"]))

    def _verify(self, photo, obs):
        """Second look: the model must back each reported symptom with visible evidence, or it is dropped. This cuts false
        alarms on plants whose normal look resembles a problem (variegation, grafted colour, natural lower-leaf fade)."""
        syms = [x for x in obs.get("symptoms", []) if x in SYMPTOM_LABELS and not x.startswith("soil_")]
        if not photo or obs.get("health") == "healthy" or obs.get("image_quality") == "poor" or not syms:
            return obs
        ask = ("An earlier look at this photo reported these symptoms:\n" + "\n".join(f"- {k}: {SYMPTOM_LABELS[k]}" for k in syms)
               + '\n\nLook again. For EACH one, say whether you can clearly point to it in the photo. Many plants look odd when normal '
               '(variegation, grafted colour on cacti, natural fading of old lower leaves). Output ONLY JSON like '
               '{"<id>": {"visible": "yes|no|unsure", "evidence": "<under 12 words: where you see it>"}}. Answer "no" if you cannot point to it.')
        try:
            reply = self.vlm.chat([{"role": "user", "content": [{"type": "image_path", "path": photo}, {"type": "text", "text": ask}]}], 400, 0.0, "Verify symptoms (second look)")
            verdict = parse_json(reply)
        except Exception:
            return obs                                   # best effort: keep the original reading if the check fails
        if not isinstance(verdict, dict): return obs
        vis = lambda k: str((verdict.get(k) or {}).get("visible", "yes")).lower() if isinstance(verdict.get(k), dict) else "yes"
        kept = [k for k in obs["symptoms"] if k not in syms or vis(k) == "yes"]
        if len(kept) == len(obs["symptoms"]): return obs
        raw = {k: v for k, v in obs.items() if not k.startswith("_")}
        raw["symptoms"] = kept
        raw["other_visible"] = [o for o in raw.get("other_visible") or [] if OTHER_TO_SYMPTOM.get(o, o) in kept or o not in OTHER_TO_SYMPTOM]
        hard = [k for k in syms if k not in kept]
        if not [k for k in kept if k in syms]:               # nothing visible survived
            raw["health"] = "unclear" if any(vis(k) == "unsure" for k in hard) else "healthy"
        out, _ = clean_observation(raw)
        out["_dropped_symptoms"] = hard
        return out

    def locate_regions(self):
        if self.regions is not None: return self.regions
        with span("tool", "Build symptom map") as a:
            out = self._locate_regions()
            a["regions"] = len(out)
            return out

    def _locate_regions(self):
        """Visual symptom map: ask the model where each observed symptom is. Returns [{symptom, label, x, y, w, h}] with
        coordinates as 0-1 fractions of the image. Best effort: any failure gives an empty map, never an error."""
        o = self.observation
        if self.regions is not None: return self.regions
        if not self.photo or not o or o.get("health") == "healthy" or not o.get("symptoms"):
            return []
        syms = {s: SYMPTOM_LABELS[s] for s in o["symptoms"] if s in SYMPTOM_LABELS}
        ask = ("Locate where these visible symptoms appear on the plant in the photo:\n"
               + "\n".join(f"- {k}: {v}" for k, v in syms.items())
               + '\n\nOutput ONLY a JSON list. Each item: {"symptom": "<id from the list>", "bbox": [x1, y1, x2, y2]} with coordinates '
               "on a 0-1000 scale relative to the image width and height. Give 1 to 5 boxes, tightly around the affected areas only "
               "(not the whole plant unless the symptom covers it). If you cannot see a symptom clearly, leave it out.")
        regions = []
        try:
            reply = self.vlm.chat([{"role": "user", "content": [{"type": "image_path", "path": self.photo}, {"type": "text", "text": ask}]}], 400, 0.0, "Locate symptom regions")
            # tolerant parse: the model sometimes emits slightly broken JSON, so pull out each item on its own
            nums = r"(-?\d+(?:\.\d+)?)"
            for sym, *box in re.findall(r'"symptom"\s*:\s*"(\w+)"\s*,\s*"bbox"\s*:\s*\[\s*' + r"\s*,\s*".join([nums] * 4), reply):
                x1, y1, x2, y2 = (max(0.0, min(1000.0, float(v))) / 1000 for v in box)
                if x2 < x1: x1, x2 = x2, x1
                if y2 < y1: y1, y2 = y2, y1
                if sym not in syms or x2 - x1 < 0.02 or y2 - y1 < 0.02: continue
                dup = next((r for r in regions if _iou(r, (x1, y1, x2 - x1, y2 - y1)) > 0.7), None)
                if dup:                                  # same area flagged for several symptoms: one box, joined label
                    if syms[sym] not in dup["label"]: dup["label"] += " / " + syms[sym]
                    continue
                regions.append({"symptom": sym, "label": syms[sym], "x": round(x1, 4), "y": round(y1, 4),
                                "w": round(x2 - x1, 4), "h": round(y2 - y1, 4)})
        except Exception:
            regions = []
        self.regions = regions[:6]
        return self.regions

    def _update(self, text):
        """Fold the user's answer into the existing observation (plant name, soil, etc.)."""
        prev = {k: v for k, v in self.observation.items() if not k.startswith("_")}
        msg = (f"Current observation:\n{json.dumps(prev)}\n\nThe user says: \"{text}\"\n\nOutput ONLY the updated observation JSON. "
               "Use the plant name the user gave with confidence high. Add only what the user stated; keep everything else.")
        with span("context", "Fold user's answer into plant findings"):
            reply = self.vlm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}], 500, 0.0, "Update findings from answer")
            try:
                raw = parse_json(reply)
            except ValueError:
                raw = None
            return clean_observation(raw)[0] if raw else self.observation

    def ensure_observation(self, photo=None, text=""):
        with self.lock:
            if self.observation is None:
                self.photo = photo
                self.observation, _ = self._observe(photo, text)
            return self.observation

    def stage(self, answered=False):
        """Where the conversation is: ask_photo | healthy | confirm_plant | ask_questions | diagnose."""
        o = self.observation
        if o.get("image_quality") == "poor": return "ask_photo"
        if o.get("health") == "healthy": return "healthy"
        if not o.get("symptoms"): return "need_closeup"
        if (o.get("plant") or {}).get("confidence") != "high" and not answered: return "confirm_plant"
        return "diagnose" if answered else "ask_questions"

    def search(self):
        """Only search the KB when there is (or may be) a problem; healthy or unusable photos skip retrieval."""
        o = self.observation
        if o.get("image_quality") == "poor" or o.get("health") == "healthy" or not o.get("symptoms"):
            trace.event("retrieval", "KB search skipped", reason="healthy, unusable photo, or no symptoms")
            return {"results": [], "coverage": "skipped", "filters_applied": {}, "filters_relaxed": [], "questions": [], "debug": {}}
        with span("retrieval", "KB search (BM25 + vector)", symptoms=o["_retrieval"]["symptoms"], plant=o["_retrieval"]["plant"]) as a:
            kb = retrieve(o["_retrieval"])
            dbg = kb["debug"]
            a.update(coverage=kb["coverage"], results=len(kb["results"]), filters_relaxed=kb["filters_relaxed"],
                     after_prefilter=len(dbg["filtered_ids"]), keyword_candidates=len(dbg["keyword_ids"]), vector_candidates=len(dbg["vector_ids"]),
                     top=[{"id": r["record"]["record_id"], "score": r["score"]} for r in kb["results"]])
            return kb

    def to_state(self):
        """JSON-safe snapshot so a conversation can resume after a restart without replaying model calls."""
        return {"observation": self.observation, "history": self.history, "qa_history": self.qa_history, "diag_turns": self.diag_turns,
                "turns": self.turns, "photo": self.photo, "stage": self.last.get("stage"), "intent": self.last.get("intent")}

    @classmethod
    def from_state(cls, st, vlm=None):
        s = cls(vlm)
        s.observation, s.history, s.qa_history = st.get("observation"), st.get("history", []), st.get("qa_history", [])
        s.diag_turns, s.turns, s.photo = st.get("diag_turns", 0), st.get("turns", 0), st.get("photo")
        s.last = {"stage": st.get("stage"), "intent": st.get("intent"), "kb": {"results": []}}
        return s

    def route(self, text, photo=None, skill=""):
        """Decide whether this message needs the diagnosis skill: diagnose | answer | question | offtopic."""
        text = (text or "").strip()
        low = text.lower()
        if skill == "diagnose" or low.startswith(DIAGNOSE_COMMANDS):
            return "diagnose"
        if photo and not text:
            return "diagnose"
        awaiting = self.diag_turns > 0 and self.last.get("stage") in ("confirm_plant", "ask_questions", "need_closeup")
        key = (text, bool(photo), awaiting)
        with self.lock:
            if key not in self.route_cache:
                ctx = f"has_photo: {'yes' if photo else 'no'}\nawaiting_answers_to_assistant_questions: {'yes' if awaiting else 'no'}\n"
                if awaiting: ctx += f"assistant's last message: {self.history[-1]['content'][:400]}\n"
                reply = self.vlm.chat([{"role": "system", "content": ROUTER}, {"role": "user", "content": ctx + f'user message: "{text}"'}], 5, 0.0, "Route message").strip().upper()
                intent = next((w.lower() for w in ("DIAGNOSE", "ANSWER", "QUESTION", "OFFTOPIC") if w in reply), "diagnose" if photo else "question")
                if intent == "answer" and not awaiting: intent = "diagnose" if self.diag_turns == 0 and photo else "question"
                self.route_cache[key] = intent
            return self.route_cache[key]

    def turn(self, text="", photo=None, extra_context="", skill="", parts=None):
        """parts = {"profile": ..., "history": ...}: the pieces of extra_context, only used to label the context-window meter."""
        with span("wait", "Waiting for the session lock"): self.lock.acquire()
        try:
            self._parts = parts or {}
            return self._dispatch(text, photo, extra_context, skill)
        finally:
            self.lock.release()

    def _dispatch(self, text, photo, extra_context, skill):
        if text.strip().lower().startswith(DIAGNOSE_COMMANDS):
            skill, text = "diagnose", re.sub(r"^/\w+\s*", "", text.strip())
        intent = self.route(text, photo, skill)
        self.turns += 1
        if intent == "offtopic":
            reply = "I can only help with plants. Send a photo or ask me about your plant."
            self.last = {"intent": intent, "stage": self.last.get("stage"), "kb": self.last.get("kb", {"results": []})}
            return reply
        if intent in ("diagnose", "answer"):
            if intent == "diagnose" and self.diag_turns > 0:
                if photo and photo != self.photo or not photo:
                    self._reset()               # a new photo, or an explicit re-check, starts a fresh diagnosis
                    photo = photo or self.photo # a re-check without a new photo reuses the last one
            reply = self._turn(text, photo, extra_context)
            self.last["intent"] = intent
            return reply
        return self._general(text, photo, extra_context)

    def _reset(self):
        self.observation, self.history, self.diag_turns, self.regions = None, [], 0, None

    @staticmethod
    def _user_text(m):
        c = m["content"]
        return c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if x["type"] == "text")

    def _record_context(self, skill, findings, rag, history, answers, extra_context, has_image):
        """Break the prompt just sent into labelled segments and publish it to the trace (the context-window meter).
        Text is estimated at ~4 chars/token; image tokens are whatever the provider's real prompt count says is left over."""
        parts = getattr(self, "_parts", {})
        profile, journal = parts.get("profile", extra_context or ""), parts.get("history", "")
        rest = max(0, tok(extra_context) - tok(profile) - tok(journal)) if extra_context else 0      # e.g. the SOS/healthy mode hint
        segs = [("skill", "Skill instructions", tok(skill) + rest), ("profile", "Plant profile", tok(profile)),
                ("findings", "Image findings", tok(findings)), ("history", "History", tok(journal) + tok(history)),
                ("answers", "User answers", tok(answers)), ("rag", "RAG chunks", tok(rag))]
        text_total = sum(t for _, _, t in segs)
        u = self.vlm.last_usage
        images = (max(0, u["prompt_tokens"] - text_total) if u else 576) if has_image else 0
        segs += [("images", "Photo", images), ("reply", "This reply", u["completion_tokens"] if u else 0)]
        exact = bool(u and u["source"] == "provider")
        used = u["prompt_tokens"] + u["completion_tokens"] if exact else sum(t for _, _, t in segs)    # segments are estimates; the total is the provider's count
        trace.context([{"key": k, "label": l, "tokens": t} for k, l, t in segs], NUM_CTX, used, exact=exact)

    def _general(self, text, photo, extra_context):
        """Plain answer to a care question. No skill format, no causes, no checklist unless the user asks."""
        if photo and self.observation is None:
            self.ensure_observation(photo, "")
        o = self.observation
        ctx, found, earlier = [], "", ""
        if o:
            pl = o.get("plant") or {}
            found = (f"From the photo: plant looks like {pl.get('name', 'unknown')} (confidence {pl.get('confidence', 'unknown')}); "
                     f"health: {o.get('health')}; visible symptoms: {', '.join(o.get('symptoms') or []) or 'none'}.")
            ctx.append(found)
        if self.history and self.history[-1]["role"] == "assistant":
            earlier = "Earlier you told the user: " + self.history[-1]["content"][:1200]
            ctx.append(earlier)
        if extra_context: ctx.append("Saved plant context: " + extra_context)
        msgs = [{"role": "system", "content": GENERAL}, {"role": "user", "content": "CONTEXT (do not repeat it):\n" + "\n".join(ctx or ["No photo yet."])}]
        msgs += self.qa_history[-6:] + [{"role": "user", "content": text}]
        reply = split_reply(self.vlm.chat(msgs, 450, 0.3, "Answer plant question"))
        prior = self.qa_history[-6:]
        self._record_context(GENERAL, found, "", earlier + " ".join(m["content"] for m in prior if m["role"] == "assistant"),
                             " ".join(m["content"] for m in prior if m["role"] == "user") + " " + text, extra_context, False)
        self.qa_history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        self.last = {"intent": "question", "stage": self.last.get("stage"), "kb": self.last.get("kb", {"results": []}), "observation": o, "reply": reply}
        return reply

    def _turn(self, text, photo, extra_context):
        first = self.diag_turns == 0
        if self.observation is None:
            self.ensure_observation(photo, text)
        elif text and not first:
            self.observation = self._update(text)
        self.diag_turns += 1
        prior = list(self.history)                      # everything before this turn, for the context-window accounting
        kb = self.search()
        records = [{"record_id": r["record"]["record_id"], "cause": r["record"]["cause"], "category": r["record"]["cause_category"],
                    "summary": r["record"]["summary"], "distinguishing_questions": [q["question"] for q in r["record"]["distinguishing_questions"]],
                    "next_actions": r["record"]["next_actions"], "inspect_next": r["record"]["inspect_next"],
                    "caveats": r["record"]["caveats"], "source_url": r["record"]["source_url"]} for r in kb["results"]]
        ctx = ("KNOWLEDGE BASE RESULT (application-supplied; use only these records, cite them as [rec_...]):\n"
               + json.dumps({"coverage": kb["coverage"], "filters_relaxed": kb["filters_relaxed"], "records": records,
                             "suggested_questions": kb["questions"]}, indent=1)
               + (f"\n\nPLANT CONTEXT (from the user's saved profile and history; not a source of causes):\n{extra_context}" if extra_context else "")
               + "\n\nOBSERVATION:\n" + json.dumps({k: v for k, v in self.observation.items() if not k.startswith("_")})
               + f"\n\nSECTIONS YOU MAY WRITE THIS TURN: {allowed_sections(self.observation, kb['coverage'], not first)}.\nTreat as fact only what the photo shows or the user wrote; never state that the user said something they did not.\n{FORMAT}")
        content = ([{"type": "image_path", "path": photo}] if first and photo else []) + [{"type": "text", "text": (text or "Here is my plant.") + "\n\n" + ctx}]
        self.history.append({"role": "user", "content": content})
        reply = split_reply(self.vlm.chat([{"role": "system", "content": SYSTEM}] + self.history, 1000, 0.3, "Write reply"))
        # keep only the plain user text in history for later turns (context block is rebuilt each turn)
        self.history[-1] = {"role": "user", "content": content[:-1] + [{"type": "text", "text": text or "Here is my plant."}]}
        report = {}
        if self.observation.get("image_quality") != "poor" and self.observation.get("health") != "healthy" and self.observation.get("symptoms") and kb["coverage"] in ("good", "weak"):
            with span("tool", "Ground reply in KB records") as a:
                reply = ground_reply(reply, kb, report)
                a.update(report)
        sent = {"records": records, "suggested_questions": kb["questions"]}
        self._record_context(SYSTEM + "\n" + FORMAT + allowed_sections(self.observation, kb["coverage"], not first),
                             {k: v for k, v in self.observation.items() if not k.startswith("_")}, sent,
                             " ".join(self._user_text(m) for m in prior if m["role"] == "assistant"),
                             " ".join(self._user_text(m) for m in prior if m["role"] == "user") + " " + (text or ""),
                             extra_context, any(isinstance(m["content"], list) and any(c["type"] != "text" for c in m["content"]) for m in self.history))
        if kb["results"]:
            cited = set(re.findall(r"\[(rec_\d+)\]", reply)) | set(report.get("used", []))
            emit_rag(kb, cited, "reply", report.get("used", []) if report.get("fallback") else [])
        asks = [q["question"] for q in kb["questions"]] if first else []       # optional questions: written by code, from the records
        if asks and self.observation.get("image_quality") != "poor" and self.observation.get("health") != "healthy":
            reply = reply.rstrip() + ("\n---\n" if "\n---\n" not in reply else "\n") + \
                    "**Optional questions** (answer any you like for a sharper answer):\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(asks, 1))
        self.history.append({"role": "assistant", "content": reply})
        self.last = {"observation": self.observation, "kb": kb, "reply": reply, "stage": self.stage(not first)}
        return reply


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--photo"); ap.add_argument("--text", default="")
    a = ap.parse_args()
    s = Session()
    print(s.turn(a.text, a.photo))
    while True:
        t = input("\nyou> ").strip()
        if not t: break
        print(s.turn(t))
