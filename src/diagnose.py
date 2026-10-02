"""Differential diagnosis: rank the retrieved candidate causes, fold in the user's yes/no answers to the records' own
distinguishing questions, and decide a status (confirmed / likely / undetermined). Decided in code from the records and the
user's answers, so the reply states a verdict the evidence supports and asks for the one thing that would settle it.
assess() is pure (offline-testable); extract_answers() is the only model call and only reads what the user wrote."""
import json
import re

CONFIRM_SUPPORT, CONFIRM_MARGIN = 2, 2.0     # answers supporting the leader / score lead over the runner-up needed to call it confirmed
LIKELY_MARGIN = 1.0


def _delta(answer, q):
    """+2 when the answer supports the cause, -2 when it weakens or rules it out, 0 when the record says nothing."""
    t = (q["if_yes"] if answer == "yes" else q["if_no"]).lower()
    return 2.0 if "support" in t else -2.0 if ("weaken" in t or "rule" in t) else 0.0


def _count(x):
    return len(x) if hasattr(x, "__len__") else int(x or 0)


def assess(kb, evidence):
    """kb: retrieve() output. evidence: {question text: 'yes'|'no'}. Returns the diagnosis dict (status 'none' without candidates)."""
    evidence = evidence or {}
    cands = []
    for rank, r in enumerate(kb.get("results", [])):
        rec = r["record"]
        score = max(0, 3 - rank) * 0.5 + _count(r.get("symptom_overlap")) * 0.75 + (0.5 if r.get("keyword_hit") else 0.0)
        sup, against, asked = [], [], set()
        for q in rec["distinguishing_questions"]:
            ans = evidence.get(q["question"])
            if ans not in ("yes", "no"): continue
            asked.add(q["question"])
            d = _delta(ans, q); score += d
            if d > 0: sup.append(f"{q['question'].rstrip('?')}? {ans}")
            elif d < 0: against.append(f"{q['question'].rstrip('?')}? {ans}")
        cands.append({"cause": rec["cause"], "record_id": rec["record_id"], "category": rec["cause_category"], "score": round(score, 2),
                      "supporting": sup, "against": against,
                      "unasked": [q["question"] for q in rec["distinguishing_questions"] if q["question"] not in evidence],
                      "inspect": rec["inspect_next"][:1]})
    if not cands:
        return {"status": "none", "headline": "", "leading": None, "alternatives": [], "ruled_out": [], "confirm": [], "supporting": [], "against": []}
    cands.sort(key=lambda c: (-c["score"], c["record_id"]))
    lead, rest = cands[0], cands[1:]
    margin = lead["score"] - rest[0]["score"] if rest else 99.0
    if len(lead["supporting"]) >= CONFIRM_SUPPORT and not lead["against"] and margin >= CONFIRM_MARGIN: status = "confirmed"
    elif margin >= LIKELY_MARGIN or (lead["supporting"] and not lead["against"] and margin > 0): status = "likely"
    else: status = "undetermined"
    ruled_out = [c["cause"] for c in rest if c["against"] and not c["supporting"]]
    alts = [c for c in rest if c["cause"] not in ruled_out][:2]
    confirm = []
    if status != "confirmed":
        for c in [lead] + alts[:1]:                    # the leader's open questions first, then the closest rival's, to tell them apart
            if c["unasked"]: confirm.append({"question": c["unasked"][0], "about": c["cause"], "record_id": c["record_id"]})
        if status == "likely" and len(confirm) < 2 and lead["unasked"][1:]:
            confirm.append({"question": lead["unasked"][1], "about": lead["cause"], "record_id": lead["record_id"]})
    headline = {"confirmed": f"Diagnosis: {lead['cause']}. Your answers support it and nothing you said argues against it.",
                "likely": f"Most likely: {lead['cause']}. Not confirmed yet.",
                "undetermined": ("I can't tell " + " from ".join(c["cause"] for c in [lead] + alts[:1]) + " yet.") if alts else f"Possible: {lead['cause']}."}[status]
    return {"status": status, "headline": headline, "leading": {k: lead[k] for k in ("cause", "record_id", "category", "score")},
            "alternatives": [{k: c[k] for k in ("cause", "record_id", "category", "score")} for c in alts], "ruled_out": ruled_out,
            "supporting": lead["supporting"], "against": lead["against"], "confirm": confirm, "inspect": lead["inspect"]}


def diagnosis_text(dx):
    """Markdown block appended to the reply's detail. Empty when there are no candidates."""
    if dx["status"] == "none": return ""
    out = [f"**Diagnosis ({dx['status']}):** {dx['headline']}"]
    if dx["supporting"]: out.append("- Supported by: " + "; ".join(dx["supporting"]))
    if dx["against"]: out.append("- Against: " + "; ".join(dx["against"]))
    if dx["ruled_out"]: out.append("- Unlikely given your answers: " + ", ".join(dx["ruled_out"]))
    if dx["confirm"]:
        out.append("**To confirm, tell me:**\n" + "\n".join(f"{i}. {c['question']} (about {c['about']})" for i, c in enumerate(dx["confirm"], 1)))
    elif dx["status"] == "confirmed" and dx["inspect"]:
        out.append("**To be sure before acting:** " + dx["inspect"][0].rstrip(".") + ".")
    return "\n".join(out)


def extract_answers(vlm, text, questions):
    """Map the user's message onto the open questions. Returns {question: 'yes'|'no'} for those the user clearly answered."""
    if not text or not questions: return {}
    listing = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    ask = (f"Questions the assistant asked or may ask about the user's plant:\n{listing}\n\nThe user wrote: \"{text}\"\n\n"
           'Output ONLY JSON: {"answers": [{"q": <number>, "a": "yes" or "no"}]} listing only the questions the user\'s message clearly answers. '
           'Use {"answers": []} if none. Never guess an answer the user did not give.')
    try:
        reply = vlm.chat([{"role": "user", "content": ask}], 150, 0.0, "Read answers to the questions")
        m = re.search(r"\{.*\}", reply, re.S)
        out = {}
        for x in json.loads(m.group(0)).get("answers", []):
            i, a = int(x["q"]), str(x["a"]).lower()
            if 1 <= i <= len(questions) and a in ("yes", "no"): out[questions[i - 1]] = a
        return out
    except Exception:
        return {}


GENERIC_ASKS = ["Which part of the plant is affected (new leaves, old leaves, stem, roots)?", "How long has it looked like this, and did anything change recently?",
                "How often do you water it, and does the soil stay wet or dry out fast?"]
CANT = re.compile(r"\b(could not|couldn't|can't|cannot|unable to) (confirm|tell|say|find)|\b(not sure|don't know|do not know)\b|won't list causes", re.I)


def clarify(vlm, situation, text="", have=""):
    """When the app cannot answer or pin down a cause, ask for the details that would let it. Questions only, never facts or advice.
    Falls back to generic questions if the model call fails."""
    ask = (f"You are a plant helper that could not answer yet. Situation: {situation}\nUser's message: \"{text or '(a photo)'}\"\n"
           + (f"What is already known: {have}\n" if have else "")
           + "Write 2 or 3 short, specific questions the user can answer (what they can see, what they did, the plant's conditions) that would help you answer. "
             "Do not repeat what is already known. Output ONLY the questions, one per line, each ending with '?'. No advice, no facts.")
    try:
        lines = [re.sub(r"^\s*(?:[-*\d.)]+\s*)", "", l).strip() for l in vlm.chat([{"role": "user", "content": ask}], 150, 0.2, "Ask for missing details").splitlines()]
        qs = list(dict.fromkeys(l for l in lines if l.endswith("?") and 8 < len(l) < 200))[:3]
    except Exception:
        qs = []
    return qs or GENERIC_ASKS[:2]


def clarify_text(qs):
    return "**I can't answer this confidently yet. To help me, tell me:**\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1)) if qs else ""
