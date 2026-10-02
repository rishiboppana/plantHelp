"""The model's `schedule_reminders` tool. After every chat reply the model itself decides whether the exchange contains a plan or a follow-up
(no keyword matching) and, if so, calls this tool with structured reminders, which are then created in Apple Reminders."""
import json, re
from datetime import date, datetime, timedelta
import reminders
from src import trace

TOOL_PROMPT = """You decide whether an assistant's reply to a plant owner contains something to put in their reminders app.
Tool: schedule_reminders(reminders: [{{title, start, time, repeat_every_days}}])
- Call it only for actions the reply tells the owner to DO at a specific later time or repeatedly (water in 2 days, mist every evening, re-check next week), or follow-ups the owner asked to be reminded about.
- Do not include things to do right now, vague advice, or things that are only possibilities.
- title: 2-5 words, e.g. "Water the plant", "Re-check leaf undersides".
- start: YYYY-MM-DD, the first day (today is {today}). time: HH:MM 24h; evening=18:00, morning=08:00, afternoon=14:00, night=20:00, otherwise 09:00.
- repeat_every_days: integer for recurring (every evening -> 1, weekly -> 7), otherwise null.
Reply with ONLY JSON: {{"reminders": []}} or {{"reminders": [{{"title": "...", "start": "YYYY-MM-DD", "time": "HH:MM", "repeat_every_days": null}}]}}"""


def _items(data):
    out = []
    for r in (data.get("reminders") or [])[:6]:
        try:
            h, m = (int(x) for x in str(r.get("time") or "09:00").split(":")[:2])
            start = date.fromisoformat(str(r["start"])[:10])
            if not 0 <= (start - date.today()).days <= 365: continue
            n = int(r["repeat_every_days"]) if r.get("repeat_every_days") else None
            out.append({"title": str(r["title"]).strip()[:80], "start": start, "time": (h, m), "every_days": n if n and n > 0 else None})
        except (KeyError, ValueError, TypeError): continue
    return out


def tool_call(user_text, reply):
    """Ask the model to call schedule_reminders. Returns the parsed items, or None if the model call itself failed."""
    from src.remote_vlm import RemoteVLM
    msgs = [{"role": "system", "content": TOOL_PROMPT.format(today=date.today().isoformat())},
            {"role": "user", "content": f"OWNER SAID:\n{(user_text or '')[:600]}\n\nASSISTANT REPLY:\n{reply[:2500]}"}]
    try:
        raw = RemoteVLM().chat(msgs, 300, 0.0, "Tool call: schedule_reminders")
        m = re.search(r"\{.*\}", raw, re.S)
        return _items(json.loads(m.group(0))) if m else []
    except Exception:
        return None


def process_reply(plant_id, user_text, reply):
    """Run after each chat reply. Returns {"added": [...], "errors": [...]} or None when the model scheduled nothing."""
    if not reminders.auto_enabled() or not (reply or "").strip(): return None
    with trace.span("tool", "Apple Reminders") as a:
        items = tool_call(user_text, reply)
        if items is None: a["error"] = "tool call failed"; return None
        a["model_requested"] = len(items)
        if not items: return None
        res = reminders.create_items(plant_id, items)
        a.update(scheduled=len(res["added"]), already=len(res["already_scheduled"]), errors=[e["error"] for e in res["errors"]][:2])
    return res if (res["added"] or res["errors"]) else None


def sync_followup(plant_id, title, due_iso, hour=18):
    """Mirror an in-app follow-up (the post-check-up re-check) into Apple Reminders."""
    if not reminders.auto_enabled(): return None
    d = date.fromisoformat(due_iso[:10])
    return reminders.create_items(plant_id, [{"title": title, "start": d, "time": (hour, 0), "every_days": None}])
