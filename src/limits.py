"""Real context window of the model that serves a call. The Hugging Face router lists `context_length` per provider at
GET {base}/models, so "Qwen/Qwen3-VL-30B-A3B-Instruct:novita" and ":deepinfra" can have different limits.
PLANTLENS_CTX overrides the lookup; ASSUMED is used (and labelled so) when the router does not say."""
import json, os, threading, time, urllib.request

ASSUMED = 32768
_cache = {"data": None, "at": 0.0}
_lock = threading.Lock()


def _listing(base_url, ssl_ctx):
    """{model_id: {provider: context_length | None}}, cached for an hour (a failed fetch is retried after a minute)."""
    with _lock:
        age = time.time() - _cache["at"]
        if _cache["data"] is not None and age < (3600 if _cache["data"] else 60): return _cache["data"]
        data = {}
        if ssl_ctx is None:
            try:
                import certifi, ssl
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                pass
        try:
            req = urllib.request.Request(base_url.rstrip("/") + "/models", headers={"User-Agent": "plantlens/0.1"})
            with urllib.request.urlopen(req, timeout=4, context=ssl_ctx) as r:
                for m in json.load(r).get("data", []):
                    data[m["id"]] = {p.get("provider"): p.get("context_length") for p in m.get("providers", [])}
        except Exception:
            pass
        _cache.update(data=data, at=time.time())
        return data


def context_limit(model, base_url, ssl_ctx=None):
    """-> (tokens, source). source: env | provider | model (another provider of the same model) | assumed."""
    if os.environ.get("PLANTLENS_CTX"): return int(os.environ["PLANTLENS_CTX"]), "env"
    mid, _, provider = (model or "").partition(":")
    provs = _listing(base_url, ssl_ctx).get(mid, {})
    if provs.get(provider): return int(provs[provider]), "provider"
    known = [v for v in provs.values() if v]
    if known: return int(min(known)), "model"
    return ASSUMED, "assumed"
