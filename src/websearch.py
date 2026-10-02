"""Web search tool: used when the model says it does not know the answer. Backends, tried in order:
Tavily (if TAVILY_API_KEY, or tavily_api_key, is set; most reliable), DuckDuckGo's HTML endpoint (no key, but it often answers bots with a challenge page),
then Wikipedia's search API (no key). Sends only the short query the model wrote (never the photo or the chat). Usage: python -m src.websearch "why do calathea leaves curl"
"""
import argparse, html, json, os, re, ssl, urllib.parse, urllib.request
import src.remote_vlm  # noqa: F401  (loads .env so the key is found when this runs on its own)

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = None

SEARCH_PREFIX = "SEARCH:"
MAX_RESULTS = 4


def _clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _real_url(href):
    """DuckDuckGo wraps result links as //duckduckgo.com/l/?uddg=<encoded url>."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(href)).query)
    return q["uddg"][0] if "uddg" in q else html.unescape(href)


def tavily_key():
    """The Tavily key from the environment or .env; accepts TAVILY_API_KEY or tavily_api_key."""
    return os.environ.get("TAVILY_API_KEY") or os.environ.get("tavily_api_key") or ""


def _tavily(query, n, **extra):
    req = urllib.request.Request("https://api.tavily.com/search", method="POST",
                                 data=json.dumps({"query": query, "max_results": n, **extra}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + tavily_key()})
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        return [{"title": x["title"], "url": x["url"], "snippet": x["content"][:300]} for x in json.load(r).get("results", [])][:n]


def _wikipedia(query, n):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query, "srlimit": n, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "plantlens/0.1"}), timeout=15, context=_SSL) as r:
        rows = json.load(r)["query"]["search"]
    return [{"title": x["title"], "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(x["title"].replace(" ", "_")),
             "snippet": _clean(x["snippet"])} for x in rows]


def web_search(query, n=MAX_RESULTS):
    """Returns [{title, url, snippet}]; an empty list when every backend fails (the caller then says it could not check)."""
    backends = ([_tavily] if tavily_key() else []) + [_duckduckgo, _wikipedia]
    for b in backends:
        try:
            out = b(query, n)
        except Exception:
            continue
        if out: return out
    return []


def _duckduckgo(query, n):
    req = urllib.request.Request("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}),
                                 headers={"User-Agent": "Mozilla/5.0 (plantlens/0.1)"})
    with urllib.request.urlopen(req, timeout=15, context=_SSL) as r:
        page = r.read().decode("utf-8", "replace")
    out = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', page, re.S):
        url = _real_url(m.group(1))
        if url.startswith("http"): out.append({"title": _clean(m.group(2)), "url": url, "snippet": _clean(m.group(3))})
        if len(out) >= n: break
    return out


def parse_search_request(reply):
    """If the model answered with 'SEARCH: <query>', return the query, else None."""
    r = (reply or "").strip()
    if not r.upper().startswith(SEARCH_PREFIX): return None
    lines = r[len(SEARCH_PREFIX):].strip().splitlines()
    q = lines[0].strip(" \"'`") if lines else ""
    return q[:150] or None


def format_results(results):
    return "\n".join(f"[{i}] {r['title']} ({r['url']})\n    {r['snippet']}" for i, r in enumerate(results, 1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("query")
    for r in web_search(ap.parse_args().query): print(r)
