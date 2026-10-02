"""PlantLens pipeline: photo -> observation JSON (model) -> retrieve (local KB) -> reply (model, records only).
CLI:  python -m src.pipeline --photo test_photos/x.jpg [--text "..."]   (then type follow-up answers; empty line quits)
"""
import argparse, contextvars, json, os, re, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml
from src.remote_vlm import RemoteVLM, MODELS, BASE_URL
from src.limits import context_limit
from src.convgraph import ConvGraph, EXTRACT
from src.retrieve import retrieve
from src.identify import identify
from src.websearch import web_search, rank_results, parse_search_request, format_results
from src import trace
from src.guardrails import guard, REFUSE_IN, REFUSE_OUT
from src.trace import span, tok
from src.validate.validate import KB

SKILL = KB.parent / "plantlens"
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


def plant_from_text(text):
    """A plant the user named themselves ("it's a pothos") is trusted over any guess from the photo."""
    low = " " + re.sub(r"[^a-z0-9' ]", " ", (text or "").lower()) + " "
    hits = [n for n in PLANT_NAMES if f" {n} " in low]
    return max(hits, key=len) if hits else None


def plant_line(plant):
    """How the plant should be named, honestly: confirmed / looks like (maybe) / unknown."""
    name, conf, c = (plant or {}).get("name"), (plant or {}).get("confidence"), [x for x in (plant or {}).get("candidates", []) if x]
    others = [x for x in c if x != name][:2]
    try: shared = int(str((plant or {}).get("agree", "2/2")).split("/")[0]) >= 2
    except ValueError: shared = True
    if not shared: c, others = [], []                   # candidates nobody agrees on are noise, not alternatives
    if conf == "high" and name: return f"{name}"
    if conf == "medium" and name: return f"looks like {name}" + (f" (could also be {' or '.join(others)})" if others else "") + ", not confirmed"
    return "could not tell which plant this is" + (f" (maybe {', '.join(c[:3])})" if c else "")


CARE_FACT = re.compile(r"\b(water\w*|light|sun\w*|shade|fertili\w+|feed\w*|repot\w*|prun\w+|trim\w*|propagat\w+|toxic|poison\w*|safe|pets?|cats?|dogs?|child\w*|kids?|edible|eat\w*|temperature|cold|heat|humid\w*|mist\w*|soil|how (?:often|much|long|many)|when (?:should|to)|should i|can i)\b", re.I)


def search_query(text, obs):
    """A web query that names the plant when it is known, and asks for an authoritative toxicity source on safety questions."""
    plant = (obs or {}).get("plant") or {}
    name = plant.get("name") if plant.get("confidence") in ("high", "medium") and plant.get("name") not in (None, "unknown") else ""
    q = f"{name} {text}".strip()
    if re.search(r"toxic|safe|poison|pet|\bcats?\b|\bdogs?\b|child|kid", text or "", re.I): q += " toxicity ASPCA"
    return q[:150]


def numbers_unsupported(answer, recs):
    """True when the answer states a number (days, hours, inches...) that none of the cited records contains."""
    text = " ".join(f"{r['summary']} {' '.join(r['next_actions'])} {' '.join(r['inspect_next'])} {r.get('caveats') or ''}" for r in recs).lower()
    plain = re.sub(r"\[rec_\d+\]|\[\d+\]", "", answer)
    return [n for n in re.findall(r"\d+(?:\.\d+)?", plain) if n not in text]


def uncertainty_note(obs, kb):
    """Uncertainty mode: say plainly when the answer is a guess, and name the one extra piece of evidence that would help most."""
    recs = [r["record"] for r in kb.get("results", [])][:3]
    plant = obs.get("plant") or {}
    reasons = []
    if len(recs) >= 2 and (len({r["cause_category"] for r in recs}) >= 2 or kb.get("coverage") == "weak"): reasons.append("causes")
    if plant.get("confidence") != "high": reasons.append("plant")
    if plant.get("subject_clear") is False: reasons.append("several_plants")
    evidence = None
    for i, r in enumerate(recs):
        others = {x for j, o in enumerate(recs) if j != i for x in o["inspect_next"]}
        evidence = next((x for x in r["inspect_next"] if x not in others), None)
        if evidence: break
    if not evidence and recs:
        q = recs[0]["distinguishing_questions"]
        evidence = q[0]["question"] if q else None
    return {"reasons": reasons, "causes": [r["cause"] for r in recs], "evidence": evidence, "plant": plant_line(plant) if "plant" in reasons else None}


def uncertainty_text(note):
    """The block shown in the expandable detail; empty when there is nothing to hedge."""
    out = []
    if "causes" in note["reasons"] and len(note["causes"]) >= 2:
        out.append("These causes look alike from a photo: " + ", ".join(note["causes"][:-1]) + " and " + note["causes"][-1] + "."
                   + (f" The most useful next evidence: {note['evidence'].rstrip('.?')}." if note["evidence"] else ""))
    if note["plant"]: out.append(f"I {note['plant']}; telling me which plant it is will sharpen the advice.")
    if "several_plants" in note["reasons"]: out.append("The photo shows more than one plant, so I am describing the most prominent one.")
    return ("**Not sure yet:** " + " ".join(out)) if out else ""


DIAGNOSE_COMMANDS = ("/diagnose", "/plantlens", "/check")

ROUTER = """You route messages in a plant-care chat. Reply with ONE word:
DIAGNOSE - the user wants to find out what is wrong, or whether the plant is okay, or asks to check/diagnose a problem.
ANSWER - the message gives information in reply to the assistant's questions, such as 'yes', 'it's a cactus' or 'the soil is dry' (only possible if awaiting_answers is yes). A message that ASKS a question is never ANSWER.
QUESTION - any other plant question: care, how much to water, light, repotting, identification, what to do about one leaf, and whether a plant is toxic or safe for cats, dogs, children or people.
OFFTOPIC - not about plants.
If has_photo is yes and the message is a greeting, a statement, or asks about health, choose DIAGNOSE. With a photo, choose QUESTION only when the user asks something specific that is not about what is wrong (for example how much to water, or what plant this is)."""

GENERAL = """You are PlantLens, a friendly plant helper. Answer the user's question directly in plain language, in 2 to 5 short sentences.
Do not use headings or sections. Do not describe the photo again, list possible causes, or give a checklist unless the user asked for a diagnosis.
Use the context about the user's plant when it helps (name the plant if known, and say so if you are unsure which plant it is).
If the answer depends on things you cannot see (pot size, light, season, soil), say briefly what it depends on, and give a rough starting guide rather than a rigid schedule.
If the user describes a problem, suggest sending a photo or typing /diagnose so you can check it properly.
Never recommend specific pesticide products or doses. For pets or children eating a plant, suggest a vet or poison-control line.
If it is not about plants, say you only help with plants.
Start with ONE plain sentence that directly answers the question, alone on the first line. Only if extra detail is genuinely useful, add a line containing only --- and then the detail; otherwise stop after the first sentence.
You must NOT state plant-care facts from memory (watering amounts or schedules, light, soil, fertilizer, repotting, temperature, pests, toxicity or safety for pets or people, edibility).
Answer such questions ONLY from the REFERENCES in the context, and cite the record you used as [rec_...]. Use a reference only if it directly answers the question; do not stretch a loosely related one.
If no reference answers it, reply with exactly one line, SEARCH: <short web search query>, and nothing else.
You may answer without a reference only about the photo's plant identity or health as already described in the context, or about what you told the user earlier in this chat.
If the plant is not identified with high confidence, say which plant you are assuming, or ask which plant it is, before giving plant-specific advice."""

WEB_ANSWER = """Web search results for the user's question are below. Answer using only these results, in the same style as before (one plain sentence, optionally --- and detail).
Prefer results marked (trusted source). If none is trusted, say the answer comes from general gardening sites and is not an expert source.
Answer for the user's plant if it is named in the search query; do not give a generic answer for "indoor plants" as if it were about this plant.
Say which source you relied on by its site name. If the results do not answer the question, say you could not confirm it and suggest a local nursery or extension office. Never output SEARCH: again.
Never recommend specific pesticide products or doses."""


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
        if norm(detail).startswith(norm(summary)[:60]):
            rest = re.sub(r"^\s*" + re.escape(summary.strip().rstrip(".")) + r"\.?\s*(?:-{3,}\s*)?", "", detail, count=1).strip()
            detail = rest if len(norm(rest)) > 20 else ""   # the model repeated the summary: drop the repeat, keep anything new
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


GRAPH_AT = float(os.environ.get("PLANTLENS_GRAPH_AT", 0.85))   # share of the window at which the chat is condensed into the memory graph
CARRY_CALLS = {"Write reply", "Answer plant question"}   # the calls that carry the whole conversation; the others are one-off side calls
WARN, FULL = 0.6, 0.85                                  # share of the window at which the meter turns amber / red


def new_ledger():
    return {"calls": [], "cumulative": 0, "peak": 0, "used": 0, "limit": None, "limit_source": None, "model": None}


def context_state(ledger, turns=0):
    """What the context meter shows for one conversation. `used` is the size of the last call that carried the conversation
    (prompt + reply), i.e. what the next turn starts from; `cumulative` is every token spent on every call so far."""
    L = ledger
    limit, src, model = L["limit"], L["limit_source"], L["model"]
    if not limit:                                         # nothing sent yet: the window of the model that will be asked first
        model = MODELS[0]; limit, src = context_limit(model, BASE_URL)
    share = L["used"] / limit if limit else 0
    return {"limit": limit, "limit_source": src, "model": model, "used": L["used"], "cumulative": L["cumulative"], "peak": L["peak"],
            "turns": turns, "level": "full" if share >= FULL else "warn" if share >= WARN else "ok", "calls": L["calls"][-14:]}


class Session:
    def __init__(self, vlm=None):
        self.vlm = vlm or RemoteVLM()
        self.ledger = new_ledger()  # live token accounting for this conversation (persisted with the state)
        self.segments = []         # last prompt breakdown for the meter
        self.graph = None          # ConvGraph once the chat has filled GRAPH_AT of the window; prompts then carry graph lookups, not history
        self.log = []              # [{turn, user, assistant}] in order, across the diagnose and Q&A paths (the source for the graph)
        self.frozen = None         # plant profile + journal as they were when the conversation began; keeps every turn's prompt consistent
        self.vlm.on_usage = self._on_usage
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

    def _on_usage(self, label, u):
        """Called after every model call: put it in the ledger and publish the new meter reading right away."""
        L = self.ledger
        L["calls"].append({"label": label, "turn": self.turns, "prompt": u["prompt_tokens"], "completion": u["completion_tokens"],
                           "model": u["model"], "exact": u["source"] == "provider"})
        L["calls"] = L["calls"][-60:]
        L["cumulative"] += u["total_tokens"]
        L["peak"] = max(L["peak"], u["total_tokens"])
        L["limit"], L["limit_source"], L["model"] = u["limit"], u["limit_source"], u["model"]
        if label in CARRY_CALLS: L["used"] = u["total_tokens"]
        self._publish()

    def context_state(self):
        g = self.graph
        return {**context_state(self.ledger, self.turns), "graph": {"nodes": len(g.nodes), "edges": len(g.edges), "built_turn": g.built_turn,
                                                                    "at_tokens": self.ledger.get("condensed_at", 0)} if g else None}

    def _publish(self):
        st = self.context_state()
        trace.context(self.segments, st.pop("limit"), st.pop("used"), **st, exact=all(c["exact"] for c in st["calls"][-1:]))

    def _observe(self, photo, text):
        """Observation (symptoms, health) plus an independent, calibrated plant identification run alongside it."""
        fut = None
        if photo and not plant_from_text(text):
            ctx = contextvars.copy_context()
            fut = ThreadPoolExecutor(1).submit(ctx.run, self._identify, photo)
        obs, dropped = self._observe_raw(photo, text)
        return self._apply_identity(obs, text, fut.result() if fut else None), dropped

    def _identify(self, photo):
        with span("tool", "Identify plant (3 looks + other model families)") as a:
            r = identify(self.vlm, photo)
            a.update(name=r["name"], confidence=r["confidence"], agree=r.get("agree"), candidates=r["candidates"])
            return r

    def _apply_identity(self, obs, text, ident):
        named = plant_from_text(text)
        if named: plant = {"name": named, "confidence": "high", "source": "user"}
        elif ident: plant = {"name": ident["name"] or "unknown", "confidence": ident["confidence"], "candidates": ident["candidates"],
                             "agree": ident.get("agree"), "subject_clear": ident.get("subject_clear", True)}
        else: return obs
        raw = {k: v for k, v in obs.items() if not k.startswith("_")}
        raw["plant"] = plant
        out, _ = clean_observation(raw)
        out["_dropped_symptoms"] = obs.get("_dropped_symptoms", [])
        return out

    def _observe_raw(self, photo, text):
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
                "turns": self.turns, "photo": self.photo, "stage": self.last.get("stage"), "intent": self.last.get("intent"),
                "regions": self.regions, "ledger": self.ledger, "segments": self.segments, "frozen": self.frozen,
                "graph": self.graph.to_dict() if self.graph else None, "log": self.log}

    @classmethod
    def from_state(cls, st, vlm=None):
        s = cls(vlm)
        s.observation, s.history, s.qa_history = st.get("observation"), st.get("history", []), st.get("qa_history", [])
        s.diag_turns, s.turns, s.photo = st.get("diag_turns", 0), st.get("turns", 0), st.get("photo")
        s.regions, s.segments, s.frozen = st.get("regions"), st.get("segments", []), st.get("frozen")
        s.graph, s.log = (ConvGraph.from_dict(st["graph"]) if st.get("graph") else None), st.get("log", [])
        s.ledger = {**new_ledger(), **(st.get("ledger") or {})}
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
                if awaiting: ctx += f"assistant's last message: {self._last_assistant()[:400]}\n"
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
            ok, rail = guard.check_input(text)
            if not ok: return self._blocked(REFUSE_IN, "input", rail)
            reply = self._dispatch(text, photo, extra_context, skill)
            ok, rail = guard.check_output(reply)
            if not ok: return self._blocked(REFUSE_OUT, "output", rail)
            self._after_turn(text, reply)
            return reply
        finally:
            self.lock.release()

    def _blocked(self, reply, where, rail):
        """A guardrail stopped this turn: show the refusal, and keep the blocked text out of the history, journal and memory graph."""
        trace.event("tool", f"Guardrail blocked the {where}", rail=rail)
        for h in (self.history, self.qa_history):            # an unsafe reply was already stored by the turn: overwrite it
            if where == "output" and h and h[-1]["role"] == "assistant": h[-1] = {"role": "assistant", "content": reply}
        self.turns += 1
        self.last = {"intent": "blocked", "stage": self.last.get("stage"), "kb": {"results": []}}
        return reply

    def _after_turn(self, text, reply):
        """Log the exchange. Once the chat has used GRAPH_AT of the window it is condensed into the graph; from then on the graph grows instead."""
        self.log.append({"turn": self.turns, "user": text or "", "assistant": reply})
        if self.graph:
            self.graph.add_exchange(self.turns, text, reply)
            self.log = self.log[-4:]
        else:
            st = self.context_state()
            if st["limit"] and st["used"] >= GRAPH_AT * st["limit"]: self._condense()

    def _transcript(self):
        rows = self.log
        if not rows:                                           # a chat saved before the log existed: rebuild it from the two histories
            u = [self._user_text(m) for m in self.history if m["role"] == "user"] + [m["content"] for m in self.qa_history if m["role"] == "user"]
            a = [m["content"] for m in self.history if m["role"] == "assistant"] + [m["content"] for m in self.qa_history if m["role"] == "assistant"]
            rows = [{"turn": i + 1, "user": x, "assistant": a[i] if i < len(a) else ""} for i, x in enumerate(u)]
        obs = {k: v for k, v in (self.observation or {}).items() if not k.startswith("_")}
        return (f"PHOTO OBSERVATION: {json.dumps(obs)}\n\n" if obs else "") + "\n\n".join(
            f"[turn {r['turn']}] USER: {(r['user'] or '(photo)')[:1500]}\nASSISTANT: {r['assistant'][:2500]}" for r in rows)

    def _condense(self):
        """Turn the whole conversation into the memory graph (one model call; if it fails, every exchange becomes plain nodes)."""
        L = self.ledger
        with span("context", "Condense conversation into memory graph", used=L["used"], limit=L["limit"]) as a:
            g = ConvGraph(built_turn=self.turns)
            g.seed_from_state(self.observation, [r["record"] for r in (self.last.get("kb") or {}).get("results", [])], self.turns)
            try:
                g.merge_extracted(parse_json(self.vlm.chat([{"role": "system", "content": EXTRACT}, {"role": "user", "content": self._transcript()}],
                                                           1800, 0.0, "Condense conversation into graph")), self.turns)
            except Exception as e:
                a["extract_error"] = str(e)[:200]
                for r in self.log: g.add_exchange(r["turn"], r["user"], r["assistant"])
            self.graph, self.log = g, self.log[-4:]
            L["condensed_at"], L["used"] = L["used"], 0            # the next prompt starts small: graph lookup + the new message
            a.update(nodes=len(g.nodes), edges=len(g.edges))
        self._publish()

    def _lookup(self, text):
        with span("retrieval", "Memory graph lookup") as a:
            facts, ids = self.graph.retrieve(text)
            a.update(query=(text or "")[:120], nodes=len(ids), of=len(self.graph.nodes), picked=[self.graph.nodes[i]["text"][:90] for i in ids])
        return facts

    def _last_assistant(self):
        if self.log: return self.log[-1]["assistant"]
        h = [m for m in self.history if m["role"] == "assistant"]
        return h[-1]["content"] if h else ""

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

    def _record_context(self, skill, findings, rag, history, answers, extra_context, has_image, graph=""):
        """Break the prompt just sent into labelled segments and publish it to the trace (the context-window meter).
        Text is estimated at ~4 chars/token; image tokens are whatever the provider's real prompt count says is left over."""
        parts = getattr(self, "_parts", {})
        profile, journal = parts.get("profile", extra_context or ""), parts.get("history", "")
        rest = max(0, tok(extra_context) - tok(profile) - tok(journal)) if extra_context else 0      # e.g. the SOS/healthy mode hint
        segs = [("skill", "Skill instructions", tok(skill) + rest), ("profile", "Plant profile", tok(profile)),
                ("findings", "Image findings", tok(findings)), ("history", "History", tok(journal) + tok(history)),
                ("answers", "User answers", tok(answers)), ("rag", "RAG chunks", tok(rag)), ("graph", "Memory graph", tok(graph))]
        text_total = sum(t for _, _, t in segs)
        u = self.vlm.last_usage
        images = (max(0, u["prompt_tokens"] - text_total) if u else 576) if has_image else 0
        self.segments = segs + [("images", "Photo", images), ("reply", "This reply", u["completion_tokens"] if u else 0)]
        self.segments = [{"key": k, "label": l, "tokens": t} for k, l, t in self.segments]
        self._publish()

    def _supported(self, answer, recs):
        """Does the cited reference text actually say what the answer says? Numbers are checked in code, wording by a second model call."""
        with span("tool", "Check answer against its references") as a:
            bad = numbers_unsupported(answer, recs)
            if bad:
                a.update(unsupported_numbers=bad); return False
            body = "\n".join(f"[{r['record_id']}] {r['summary']} Advice: {'; '.join(r['next_actions'] + r['inspect_next'])} {r.get('caveats') or ''}" for r in recs)
            ask = ("REFERENCES:\n" + body + "\n\nANSWER:\n" + re.sub(r"\[rec_\d+\]", "", answer)
                   + '\n\nList every factual claim in the ANSWER that the REFERENCES do not state (even if it is true in general). '
                     'Output ONLY JSON: {"unsupported": ["claim", ...]}. Use an empty list only if every claim is stated in the references.')
            try:
                d = parse_json(self.vlm.chat([{"role": "user", "content": ask}], 250, 0.0, "Check answer against references"))
            except Exception:
                return False                    # cannot verify: do not trust it
            un = (d or {}).get("unsupported") if isinstance(d, dict) else None
            a.update(unsupported=un)
            return un == []

    def _general(self, text, photo, extra_context):
        """Plain answer to a care question. No skill format, no causes, no checklist unless the user asks."""
        if photo and self.observation is None:
            self.ensure_observation(photo, "")
        o = self.observation
        ctx, found, earlier, facts = [], "", "", ""
        if self.graph:
            facts = self._lookup(text)
            ctx.append("Conversation memory (retrieved from earlier in this chat):\n" + facts)
        elif o:
            pl = o.get("plant") or {}
            found = (f"From the photo: plant looks like {pl.get('name', 'unknown')} (confidence {pl.get('confidence', 'unknown')}); "
                     f"health: {o.get('health')}; visible symptoms: {', '.join(o.get('symptoms') or []) or 'none'}.")
            ctx.append(found)
        if not self.graph and self.history and self.history[-1]["role"] == "assistant":
            earlier = "Earlier you told the user: " + self.history[-1]["content"][:1200]
            ctx.append(earlier)
        if extra_context: ctx.append("Saved plant context: " + extra_context)
        plant = ((o or {}).get("_retrieval") or {}).get("plant") or {"id": None, "confidence": "unknown"}
        if o: ctx.append(f"Plant identity: {plant_line(o.get('plant'))}.")
        with span("retrieval", "KB references for the question") as a:
            refkb = retrieve({"plant": plant, "plant_parts": [], "symptoms": [], "location_patterns": [], "description": text})
            a.update(coverage=refkb["coverage"], results=len(refkb["results"]), top=[r["record"]["record_id"] for r in refkb["results"]])
        refs = [{"record_id": r["record"]["record_id"], "about": r["record"]["cause"], "summary": r["record"]["summary"],
                 "advice": r["record"]["next_actions"] + r["record"]["inspect_next"], "caveats": r["record"]["caveats"]} for r in refkb["results"]]
        rag = json.dumps(refs)
        ctx.append("REFERENCES (knowledge base; cite as [rec_...]; use one only if it directly answers the question):\n" + (rag if refs else "none matched this question"))
        msgs = [{"role": "system", "content": GENERAL}, {"role": "user", "content": "CONTEXT (do not repeat it):\n" + "\n".join(ctx or ["No photo yet."])}]
        prior = [] if self.graph else self.qa_history[-6:]
        msgs += prior + [{"role": "user", "content": text}]
        reply = self.vlm.chat(msgs, 450, 0.3, "Answer plant question")
        query = parse_search_request(reply)
        known = {r["record_id"] for r in refs}
        cited = [c for c in dict.fromkeys(re.findall(r"\[(rec_\d+)\]", reply)) if c in known]
        if not query and not cited and CARE_FACT.search(text or ""):
            with span("tool", "Discarded uncited care answer", draft=reply[:160]):   # a care or safety fact with no reference is not trusted
                query = search_query(text, o)
                reply = f"SEARCH: {query}"
        elif not query and cited:
            used_recs = [r["record"] for r in refkb["results"] if r["record"]["record_id"] in cited]
            if not self._supported(reply, used_recs):          # cited a record that does not actually say this
                with span("tool", "Discarded answer its references do not support", draft=reply[:160]):
                    query = search_query(text, o)
                    reply = f"SEARCH: {query}"
        if query:                                         # the model said it does not know: search the web once, then answer from the results
            with span("tool", "Web search", query=query) as a:
                results = rank_results(web_search(query))
                a.update(results=len(results), urls=[r["url"] for r in results])
            found_web = format_results(results) if results else "(no results; the search failed or found nothing)"
            msgs += [{"role": "assistant", "content": reply}, {"role": "user", "content": f"{WEB_ANSWER}\n\nSEARCH QUERY: {query}\n\nRESULTS:\n{found_web}"}]
            reply = self.vlm.chat(msgs, 450, 0.3, "Answer with web results")
            if parse_search_request(reply): reply = "I could not confirm that. A local nursery or extension office can help."
        reply = split_reply(reply)
        head0, sep0, rest0 = reply.partition("\n---\n")
        reply = re.sub(r"\s*\[\d+\]", "", head0) + sep0 + rest0
        if query and results:                             # sources go in the expandable detail, not the one-line summary
            reply = re.sub(r"\n?\*{0,2}Sources:?\*{0,2}.*", "", reply, flags=re.I).rstrip()     # drop any sources line the model wrote itself
            reply += ("\n" if "\n---\n" in reply else "\n---\n") + "**Sources:** " + ", ".join(r["url"] for r in results[:3])
        elif not query:
            reply = re.sub(r"\[(rec_\d+)\]", lambda m: m.group(0) if m.group(1) in known else "", reply)
            used = [r["record"] for r in refkb["results"] if r["record"]["record_id"] in cited]
            if used:
                head, sep, rest = reply.partition("\n---\n")
                head = re.sub(r"\s*\[rec_\d+\]", "", head).strip()                 # citations live in the detail, not the summary line
                reply = head + "\n---\n" + ((rest + "\n") if rest else "") + "**Sources:** " + ", ".join(dict.fromkeys(r["source_url"] for r in used)) \
                        + "\n**Based on:** " + "; ".join(f"{r['cause']} [{r['record_id']}]" for r in used)
                emit_rag(refkb, set(cited), "answer")
        self._record_context(GENERAL, found, rag, earlier + " ".join(m["content"] for m in prior if m["role"] == "assistant"),
                             " ".join(m["content"] for m in prior if m["role"] == "user") + " " + text, extra_context, False, facts)
        if not self.graph: self.qa_history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        self.last = {"intent": "question", "stage": self.last.get("stage"), "kb": self.last.get("kb", {"results": []}), "observation": o, "reply": reply}
        return reply

    def _turn(self, text, photo, extra_context):
        first = self.diag_turns == 0
        if self.observation is None:
            self.ensure_observation(photo, text)
        elif text and not first:
            self.observation = self._update(text)
        self.diag_turns += 1
        gm = self.graph is not None                     # graph mode: the prompt carries lookups from the memory graph instead of the history
        prior = [] if gm else list(self.history)        # everything before this turn, for the context-window accounting
        facts = self._lookup(text) if gm else ""
        kb = self.search()
        records = [{"record_id": r["record"]["record_id"], "cause": r["record"]["cause"], "category": r["record"]["cause_category"],
                    "summary": r["record"]["summary"], "distinguishing_questions": [q["question"] for q in r["record"]["distinguishing_questions"]],
                    "next_actions": r["record"]["next_actions"], "inspect_next": r["record"]["inspect_next"],
                    "caveats": r["record"]["caveats"], "source_url": r["record"]["source_url"]} for r in kb["results"]]
        ctx = ("KNOWLEDGE BASE RESULT (application-supplied; use only these records, cite them as [rec_...]):\n"
               + json.dumps({"coverage": kb["coverage"], "filters_relaxed": kb["filters_relaxed"], "records": records,
                             "suggested_questions": kb["questions"]}, indent=1)
               + (f"\n\nPLANT CONTEXT (from the user's saved profile and history; not a source of causes):\n{extra_context}" if extra_context else "")
               + (f"\n\nCONVERSATION MEMORY (retrieved from earlier in this chat; the user's own statements and what you advised):\n{facts}" if gm else "")
               + "\n\nOBSERVATION:\n" + json.dumps({**{k: v for k, v in self.observation.items() if not k.startswith("_")}, "plant": plant_line(self.observation.get("plant"))})
               + f"\n\nPLANT IDENTITY: {plant_line(self.observation.get('plant'))}. Name the plant exactly this way. Confirmed = say the name; 'looks like' = offer it as a guess "
                 "and let the user confirm; could not tell = say so and list the maybes. Never use a guessed name as fact in the advice."
               + f"\n\nSECTIONS YOU MAY WRITE THIS TURN: {allowed_sections(self.observation, kb['coverage'], not first)}.\nTreat as fact only what the photo shows or the user wrote; never state that the user said something they did not.\n{FORMAT}")
        content = ([{"type": "image_path", "path": photo}] if first and photo else []) + [{"type": "text", "text": (text or "Here is my plant.") + "\n\n" + ctx}]
        if gm: convo = [{"role": "user", "content": content}]
        else: self.history.append({"role": "user", "content": content}); convo = self.history
        reply = split_reply(self.vlm.chat([{"role": "system", "content": SYSTEM}] + convo, 1000, 0.3, "Write reply"))
        # keep only the plain user text in history for later turns (context block is rebuilt each turn)
        if not gm: self.history[-1] = {"role": "user", "content": content[:-1] + [{"type": "text", "text": text or "Here is my plant."}]}
        report = {}
        if self.observation.get("image_quality") != "poor" and self.observation.get("health") != "healthy" and self.observation.get("symptoms") and kb["coverage"] in ("good", "weak"):
            with span("tool", "Ground reply in KB records") as a:
                reply = ground_reply(reply, kb, report)
                a.update(report)
        note = uncertainty_note(self.observation, kb) if (self.observation.get("health") != "healthy" and self.observation.get("image_quality") != "poor") else None
        if note and note["reasons"]:
            block = uncertainty_text(note)
            if block:
                reply = reply.rstrip() + ("\n---\n" if "\n---\n" not in reply else "\n") + block
                if "causes" in note["reasons"] and not re.search(r"\b(not (?:sure|certain)|may|might|could|possibl|likely)\b", reply.split("\n---\n")[0], re.I):
                    head, sep, rest = reply.partition("\n---\n")
                    reply = head.rstrip(".") + " (not certain: several causes look alike)." + sep + rest
        sent = {"records": records, "suggested_questions": kb["questions"]}
        self._record_context(SYSTEM + "\n" + FORMAT + allowed_sections(self.observation, kb["coverage"], not first),
                             {k: v for k, v in self.observation.items() if not k.startswith("_")}, sent,
                             " ".join(self._user_text(m) for m in prior if m["role"] == "assistant"),
                             " ".join(self._user_text(m) for m in prior if m["role"] == "user") + " " + (text or ""),
                             extra_context, bool(photo and first) if gm else any(isinstance(m["content"], list) and any(c["type"] != "text" for c in m["content"]) for m in self.history), facts)
        if kb["results"]:
            cited = set(re.findall(r"\[(rec_\d+)\]", reply)) | set(report.get("used", []))
            emit_rag(kb, cited, "reply", report.get("used", []) if report.get("fallback") else [])
        asks = [q["question"] for q in kb["questions"]] if first else []       # optional questions: written by code, from the records
        if asks and self.observation.get("image_quality") != "poor" and self.observation.get("health") != "healthy":
            reply = reply.rstrip() + ("\n---\n" if "\n---\n" not in reply else "\n") + \
                    "**Optional questions** (answer any you like for a sharper answer):\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(asks, 1))
        if not gm: self.history.append({"role": "assistant", "content": reply})
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
