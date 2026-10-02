"""Embedders. 'hash' is a deterministic bag-of-words stand-in for offline tests; real runs use sentence-transformers."""
import hashlib, math, re

HASH_DIM = 512


def _tok(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def _hash_encode(texts):
    out = []
    for t in texts:
        v = [0.0] * HASH_DIM
        for w in _tok(t):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % HASH_DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def get_encoder(name):
    """Return encode(list[str]) -> list[list[float]] with L2-normalised vectors."""
    if name == "hash":
        return _hash_encode
    if name.startswith("sentence-transformers/"):
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(name[len("sentence-transformers/"):])
        return lambda texts: model.encode(list(texts), normalize_embeddings=True).tolist()
    raise ValueError(f"unknown embedder {name}")


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))
