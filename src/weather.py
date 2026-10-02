"""Weather impact check: geocode a place, pull the last 14 days + next 7 days (Open-Meteo, no key), and ask the model what
that weather could mean for the plant, using only the KB's environment/watering records.
Sends only the place name to Open-Meteo. Usage: python -m src.weather "San Jose" --setting outdoor
"""
import argparse, datetime, json, re, sqlite3, ssl, urllib.parse, urllib.request
from src.build_index import ROOT, load_config
from src.trace import span

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = None

CHILL_F = 50  # UC IPM and UMD (houseplant guides): chilling injury below 50°F
PAST_DAYS, FUTURE_DAYS = 14, 7
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,relative_humidity_2m_mean,uv_index_max,wind_speed_10m_max"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "plantlens/0.1"})
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        return json.load(r)


def geocode(place):
    q = urllib.parse.quote(place.split(",")[0].strip())
    res = (_get(f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=5&language=en").get("results") or [])
    if not res: return None
    hint = place.lower()
    best = next((r for r in res if any(p and p in hint for p in (str(r.get("admin1", "")).lower(), str(r.get("country", "")).lower(), str(r.get("country_code", "")).lower()))), res[0])
    return {"name": best["name"], "region": best.get("admin1", ""), "country": best.get("country", ""), "lat": best["latitude"], "lon": best["longitude"]}


def fetch(lat, lon):
    d = _get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily={DAILY}&past_days={PAST_DAYS}"
             f"&forecast_days={FUTURE_DAYS}&temperature_unit=fahrenheit&precipitation_unit=inch&wind_speed_unit=mph&timezone=auto")["daily"]
    rows = [dict(zip(d.keys(), v)) for v in zip(*d.values())]
    return rows[:PAST_DAYS], rows[PAST_DAYS:]


def stats(rows):
    def col(k): return [r[k] for r in rows if r.get(k) is not None]
    if not rows: return {}
    return {"days": len(rows), "from": rows[0]["time"], "to": rows[-1]["time"],
            "temp_low_f": min(col("temperature_2m_min")), "temp_high_f": max(col("temperature_2m_max")),
            "rain_total_in": round(sum(col("precipitation_sum")), 2), "rainy_days": sum(1 for x in col("precipitation_sum") if x >= 0.04),
            "humidity_min_pct": min(col("relative_humidity_2m_mean")) if col("relative_humidity_2m_mean") else None,
            "humidity_max_pct": max(col("relative_humidity_2m_mean")) if col("relative_humidity_2m_mean") else None,
            "uv_max": max(col("uv_index_max")) if col("uv_index_max") else None, "wind_max_mph": max(col("wind_speed_10m_max"))}


def flags(past, future):
    """Rule-based flags. Only thresholds that a source states are used (chilling below 50°F)."""
    out = []
    for label, rows in (("past", past), ("coming", future)):
        cold = [r["time"] for r in rows if r["temperature_2m_min"] is not None and r["temperature_2m_min"] < CHILL_F]
        if cold: out.append({"when": label, "kind": "cold", "days": cold,
                             "note": f"Night lows below {CHILL_F}°F on {len(cold)} day(s); the houseplant guides list chilling injury below {CHILL_F}°F."})
    return out


def weather_records():
    """Environment and watering records from the reviewed index; the only knowledge the model may use."""
    db = sqlite3.connect(ROOT / load_config()["index_path"])
    recs = [json.loads(j) for (j,) in db.execute("SELECT json FROM records ORDER BY record_id")]
    return [r for r in recs if r["cause_category"] in ("environment", "watering")]


SYSTEM = """You are PlantLens. Explain how recent and upcoming weather could affect one plant, for a home gardener.
Use ONLY the weather numbers and the KNOWLEDGE BASE RECORDS given. Cite records as [rec_...]. Do not invent temperature or humidity limits;
the only numeric limit you may use is the one stated in a record.
web_search_local_news, when present, is recent news from a web search: use it only to mention a local alert such as frost, a heat wave or a storm, name the source site, and never take a temperature limit or care rule from it. Weather rarely proves a cause, so use words like 'could' and 'may'.
If the plant is indoors, weather matters mainly through windows, drafts, heating or cooling and dry air; say so. If the setting is unknown, say what it depends on.
If the plant already shows symptoms, say whether the past weather could plausibly relate to them, as a possibility.
FORMAT: ONE plain sentence (under 25 words) as the bottom line on the first line, then a line containing only ---, then three short sections with
these exact bold headings: **Past two weeks**, **Next 7 days**, **What to watch**. Keep it brief. No pesticide products or doses."""


def local_alerts(place):
    """Recent local weather news (frost, heat wave, storm warnings) via Tavily. Best effort: no key or any failure gives []."""
    from src.websearch import tavily_key, _tavily
    if not tavily_key(): return []
    try:
        return [{"title": r["title"], "url": r["url"], "snippet": r["snippet"]}
                for r in _tavily(f"{place} weather forecast alerts frost heat wave storm this week", 3, topic="news", days=7)]
    except Exception:
        return []


def assess(vlm, place, past, future, setting, plant_ctx, records, alerts=()):
    payload = {"place": place, "plant_setting": setting or "unknown", "plant": plant_ctx,
               "past_14_days": stats(past), "next_7_days": stats(future), "flags": flags(past, future),
               "daily_past": [{k: r[k] for k in ("time", "temperature_2m_min", "temperature_2m_max", "precipitation_sum")} for r in past][-7:],
               "daily_coming": [{k: r[k] for k in ("time", "temperature_2m_min", "temperature_2m_max", "precipitation_sum")} for r in future]}
    if alerts: payload["web_search_local_news"] = list(alerts)
    recs = [{"record_id": r["record_id"], "cause": r["cause"], "category": r["cause_category"], "summary": r["summary"], "caveats": r["caveats"]} for r in records]
    msg = "DATA:\n" + json.dumps(payload) + "\n\nKNOWLEDGE BASE RECORDS:\n" + json.dumps(recs)
    from src.pipeline import split_reply
    return split_reply(vlm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}], 700, 0.3))


def check(place, setting="", plant_ctx=None, vlm=None):
    loc = geocode(place)
    if not loc: return {"error": f"Couldn't find a place called '{place}'. Try 'City, State' or 'City, Country'."}
    past, future = fetch(loc["lat"], loc["lon"])
    if vlm is None:
        from src.remote_vlm import RemoteVLM
        vlm = RemoteVLM()
    label = ", ".join(x for x in (loc["name"], loc["region"], loc["country"]) if x)
    with span("tool", "Web search (local weather news)", place=label) as a:
        alerts = local_alerts(label)
        a["results"] = len(alerts)
    return {"place": label, "setting": setting or "unknown", "past": stats(past), "future": stats(future), "flags": flags(past, future),
            "assessment": assess(vlm, label, past, future, setting, plant_ctx or {}, weather_records(), alerts),
            "alerts": alerts}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("place"); ap.add_argument("--setting", default="")
    a = ap.parse_args(); out = check(a.place, a.setting)
    print(json.dumps({k: v for k, v in out.items() if k != "assessment"}, indent=1)); print("\n" + out.get("assessment", ""))
