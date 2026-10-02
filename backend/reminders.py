"""Apple Reminders bridge: turns a care plan written in plain language ("water in 2 days", "mist every evening") into real
reminders in the macOS Reminders app, in a list called "PlantLens". Talks to Reminders through osascript, so the backend must run on a Mac
and the first call will ask for Reminders permission. Recurring plans become one reminder per occurrence over a horizon of N days
(AppleScript cannot set a repeat rule), and the same plan is never added twice."""
import re, subprocess, sys
from datetime import date, datetime, timedelta
from fastapi import APIRouter, HTTPException
import db

router = APIRouter(prefix="/api/reminders", tags=["reminders"])
LIST = "PlantLens"
TIMES = {"morning": (8, 0), "afternoon": (14, 0), "evening": (18, 0), "night": (20, 0), "tonight": (20, 0)}
ACTIONS = r"water|mist|fertili[sz]e|feed|repot|prune|trim|check|re-?check|inspect|rotate|spray|treat|monitor|flush|wipe|isolate|move|photo"
NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10, "fourteen": 14}

with db.conn() as _c:
    _c.execute("CREATE TABLE IF NOT EXISTS reminder_log(id INTEGER PRIMARY KEY, plant_id INTEGER, title TEXT, due TEXT, "
               "plan TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(plant_id, title, due))")


def _n(w):
    return int(w) if w.isdigit() else NUM.get(w, 1)


def parse_plan(text, today=None):
    """Plan text -> [{title, start (date), time (h, m), every_days (int|None), label}]. Only sentences that name an action AND a time count."""
    today = today or date.today()
    out = []
    for raw in re.split(r"[.\n;]|\s-\s", text or ""):
        s = re.sub(r"^[\s\-*•\d)]+", "", raw).strip()          # drop bullets / numbering
        low = s.lower()
        if not s or not re.search(rf"\b({ACTIONS})\b", low): continue
        hm = next((v for k, v in TIMES.items() if k in low), None)
        m = re.search(r"\bat (\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", low)
        if m:
            h = int(m[1]) % 12 + (12 if m[3] == "pm" else 0); hm = (h, int(m[2] or 0))
        every, start, found = None, today, False
        if re.search(r"\b(every day|daily|each day|every (morning|afternoon|evening|night)|each (morning|evening|night)|nightly)\b", low): every, found = 1, True
        elif re.search(r"\bevery other day\b", low): every, found = 2, True
        elif m2 := re.search(r"\bevery (\w+) days\b", low): every, found = _n(m2[1]), True
        elif m2 := re.search(r"\bevery (\w+) weeks\b", low): every, found = _n(m2[1]) * 7, True
        elif re.search(r"\b(weekly|every week|once a week)\b", low): every, found = 7, True
        if not found:
            if m2 := re.search(r"\b(?:in|after|within)\s+(\w+)\s+(day|week)s?\b", low): start, found = today + timedelta(days=_n(m2[1]) * (7 if m2[2] == "week" else 1)), True
            elif "tomorrow" in low: start, found = today + timedelta(days=1), True
            elif re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", low): found = True
        if not found: continue
        out.append({"title": s[0].upper() + s[1:], "start": start, "time": hm or (9, 0), "every_days": every})
    return out


def occurrences(item, horizon):
    """Concrete datetimes for one parsed item. One-offs give one; recurring ones every `every_days` up to `horizon` days from now."""
    h, mi = item["time"]; first = datetime.combine(item["start"], datetime.min.time()).replace(hour=h, minute=mi)
    if not item["every_days"]: return [first]
    now, end, out, d = datetime.now(), datetime.now() + timedelta(days=horizon), [], first
    while d <= end:
        if d >= now: out.append(d)
        d += timedelta(days=item["every_days"])
    return out


SCRIPT = '''on run argv
  set listName to item 1 of argv
  set theTitle to item 2 of argv
  set theNote to item 3 of argv
  set d to current date
  set year of d to (item 4 of argv as integer)
  set month of d to 1
  set day of d to 1
  set month of d to (item 5 of argv as integer)
  set day of d to (item 6 of argv as integer)
  set time of d to ((item 7 of argv as integer) * 3600 + (item 8 of argv as integer) * 60)
  tell application "Reminders"
    if not (exists list listName) then make new list with properties {name:listName}
    make new reminder at end of reminders of list listName with properties {name:theTitle, body:theNote, due date:d, remind me date:d}
  end tell
end run'''


def add_apple_reminder(title, when, note=""):
    if sys.platform != "darwin": raise RuntimeError("Apple Reminders needs macOS")
    args = ["osascript", "-e", SCRIPT, LIST, title, note, str(when.year), str(when.month), str(when.day), str(when.hour), str(when.minute)]
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if r.returncode: raise RuntimeError(r.stderr.strip() or "osascript failed")


def create_items(plant_id, items, horizon=14, dry_run=False):
    """items: [{title, start (date), time (h, m), every_days}] -> creates the reminders (skipping ones already logged)."""
    plant = (db.rows("SELECT name FROM plants WHERE id=?", (plant_id,)) or [{}])[0].get("name") or "plant"
    added, skipped, errors = [], [], []
    for it in items:
        for when in occurrences(it, horizon):
            title, due = f"{it['title']} ({plant})", when.strftime("%Y-%m-%d %H:%M")
            rec = {"title": title, "due": due, "repeats": bool(it["every_days"])}
            if db.rows("SELECT 1 FROM reminder_log WHERE plant_id=? AND lower(title)=lower(?) AND due=?", (plant_id, title, due)):
                skipped.append(rec); continue
            if not dry_run:
                try: add_apple_reminder(title, when, f"PlantLens plan for {plant}")
                except Exception as e: errors.append({**rec, "error": str(e)}); continue
                db.run("INSERT INTO reminder_log(plant_id,title,due,plan) VALUES(?,?,?,?)", (plant_id, title, due, it["title"]))
            added.append(rec)
    return {"added": added, "already_scheduled": skipped, "errors": errors, "dry_run": dry_run}


def schedule(plant_id, text, horizon=14, dry_run=False):
    return create_items(plant_id, parse_plan(text), horizon, dry_run)


# ---------- auto mode (on by default; the Reminders tab has the switch) ----------
with db.conn() as _c:
    _c.execute("CREATE TABLE IF NOT EXISTS reminder_settings(key TEXT PRIMARY KEY, value TEXT)")


def auto_enabled():
    r = db.rows("SELECT value FROM reminder_settings WHERE key='auto'")
    return not r or r[0]["value"] == "1"


@router.get("/settings")
def get_settings(): return {"auto": auto_enabled(), "supported": sys.platform == "darwin"}


@router.put("/settings")
def put_settings(body: dict):
    db.run("INSERT INTO reminder_settings(key,value) VALUES('auto',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("1" if body.get("auto") else "0",))
    return get_settings()


@router.post("/from-text")
def from_text(body: dict):
    """{plant_id, text, horizon_days=14, dry_run=false}: text is the model's plan (or any care instructions)."""
    if not (body.get("text") or "").strip(): raise HTTPException(400, "text required")
    return schedule(body.get("plant_id", 1), body["text"], int(body.get("horizon_days", 14)), bool(body.get("dry_run")))


@router.post("/from-conversation/{cid}")
def from_conversation(cid: int, body: dict = None):
    """Schedule the plan in the latest assistant message of a saved chat."""
    body = body or {}
    m = db.rows("SELECT m.content, c.plant_id FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                "WHERE m.conversation_id=? AND m.role='assistant' AND m.content!='' ORDER BY m.id DESC LIMIT 1", (cid,))
    if not m: raise HTTPException(404, "no assistant message in that chat")
    return schedule(m[0]["plant_id"], m[0]["content"], int(body.get("horizon_days", 14)), bool(body.get("dry_run")))


@router.post("")
def create(body: dict):
    """One explicit reminder: {plant_id, title, due: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM', repeat_days?: int, horizon_days?: 14}."""
    try: start = datetime.fromisoformat(body["due"])
    except (KeyError, ValueError): raise HTTPException(400, "due must be YYYY-MM-DD or YYYY-MM-DD HH:MM")
    item = {"title": body.get("title") or "Plant care", "start": start.date(), "time": (start.hour, start.minute) if " " in body["due"] or "T" in body["due"] else (9, 0),
            "every_days": int(body["repeat_days"]) if body.get("repeat_days") else None}
    plant = (db.rows("SELECT name FROM plants WHERE id=?", (body.get("plant_id", 1),)) or [{}])[0].get("name") or "plant"
    done, errors = [], []
    for when in occurrences(item, int(body.get("horizon_days", 14))):
        try: add_apple_reminder(f"{item['title']} ({plant})", when, f"PlantLens plan for {plant}")
        except Exception as e: errors.append(str(e)); break
        db.run("INSERT OR IGNORE INTO reminder_log(plant_id,title,due,plan) VALUES(?,?,?,?)", (body.get("plant_id", 1), f"{item['title']} ({plant})", when.strftime("%Y-%m-%d %H:%M"), item["title"]))
        done.append(when.strftime("%Y-%m-%d %H:%M"))
    return {"added": done, "errors": errors}


@router.get("")
def list_log(plant_id: int = 0):
    """Reminders PlantLens has created (its own log; deleting one in the Reminders app does not remove the row)."""
    return db.rows("SELECT * FROM reminder_log WHERE (?=0 OR plant_id=?) ORDER BY due", (plant_id, plant_id))
