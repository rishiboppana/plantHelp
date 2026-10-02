# Retrieval results (running log)

## 2026-10-02 — embedder `hash`

56 queries (in-scope + out-of-scope), K=5, config: rrf_k=60, N_kw=20, N_vec=20, min_viable=3, vec_min_score=0.35

| config | recall@5 | hit@5 | MRR | coverage acc |
|---|---|---|---|---|
| vector only | 0.946 | 0.962 | 0.868 | 0.964 |
| keyword only | 0.990 | 1.000 | 0.949 | 0.964 |
| hybrid, no prefilter | 0.971 | 0.981 | 0.918 | 0.964 |
| hybrid + prefilter | 0.946 | 0.981 | 0.918 | 0.964 |

Miss categories (hybrid + prefilter): {'c': 4, 'd': 1}

<details><summary>Misses</summary>

- q011 [lay] (c) stem base is mushy and smells bad and the plant is collapsing  expected=['rec_000025', 'rec_000001'] got=['rec_000025', 'rec_000026', 'rec_000014']
- q023 [lay] (c) newest leaves are yellow-green while older ones are fine  expected=['rec_000006', 'rec_000001'] got=['rec_000005', 'rec_000006', 'rec_000013', 'rec_000018', 'rec_000016']
- q046 [vocab] (d) the plant froze near the window and now leaves are dead  expected=['rec_000009'] got=['rec_000013', 'rec_000008', 'rec_000025', 'rec_000017', 'rec_000003']
- q050 [filter] (c) jade plant drooping with soft base  expected=['rec_000001', 'rec_000025'] got=['rec_000025', 'rec_000026', 'rec_000014']
- q052 [filter] (c) peace lily with brown tips  expected=['rec_000004', 'rec_000002', 'rec_000010'] got=['rec_000010', 'rec_000029', 'rec_000004']
- q053 [oos] expected none, got weak: my dog chewed the pot and the saucer cracked
- q055 [oos] expected none, got weak: what is the capital of France

</details>

## 2026-10-02 — embedder `hash`

56 queries (in-scope + out-of-scope), K=5, config: rrf_k=60, N_kw=20, N_vec=20, min_viable=3, vec_min_score=0.35

| config | recall@5 | hit@5 | MRR | coverage acc |
|---|---|---|---|---|
| vector only | 0.946 | 0.962 | 0.868 | 0.982 |
| keyword only | 0.990 | 1.000 | 0.942 | 0.982 |
| hybrid, no prefilter | 0.971 | 0.981 | 0.942 | 0.982 |
| hybrid + prefilter | 0.971 | 0.981 | 0.942 | 0.982 |

Miss categories (hybrid + prefilter): {'d': 2}

<details><summary>Misses</summary>

- q023 [lay] (d) newest leaves are yellow-green while older ones are fine  expected=['rec_000006', 'rec_000001'] got=['rec_000005', 'rec_000006', 'rec_000013', 'rec_000011', 'rec_000018']
- q046 [vocab] (d) the plant froze near the window and now leaves are dead  expected=['rec_000009'] got=['rec_000013', 'rec_000008', 'rec_000010', 'rec_000007', 'rec_000019']
- q053 [oos] expected none, got weak: my dog chewed the pot and the saucer cracked

</details>

## Notes on the two runs above (2026-10-02, `hash` embedder, a stand-in, NOT a real embedding model)

- Run 1 (baseline): hybrid + prefilter scored below keyword-only and no-prefilter (recall@5 0.946 vs 0.990/0.971). 4 of 5 misses were category (c): the plant-part filter excluded whole-plant records (e.g. overwatering, underwatering) when the query named `stem` or `leaf`.
- Adjustment: records with part `whole_plant` now pass any part filter; and common words are dropped from the keyword query (this fixed "capital of France" returning `weak`).
- Run 2: hybrid + prefilter equals hybrid without prefilter (recall@5 0.971, MRR 0.942). The prefilter is therefore neutral on this 29-record corpus, not helpful yet. It should be re-checked with a larger corpus and plant-specific records, where it should matter more.
- Remaining misses: q023 (ranking: overwatering not top-5 for "newest leaves yellow-green"), q046 ("froze" vs cold injury, a vocabulary gap the hash embedder cannot bridge), q053 (out-of-scope text got `weak` not `none`).
- TODO: rerun on Colab with `BAAI/bge-small-en-v1.5` and at least one other model (Phase 6 requires two); keep the one with the best recall@K.
- The 56 queries and expected ids were written by the same author as the records; the owner should review them.

## 2026-10-02 — embedder `sentence-transformers/BAAI/bge-small-en-v1.5`

56 queries (in-scope + out-of-scope), K=5, config: rrf_k=60, N_kw=20, N_vec=20, min_viable=3, vec_min_score=0.35

| config | recall@5 | hit@5 | MRR | coverage acc |
|---|---|---|---|---|
| vector only | 0.965 | 1.000 | 0.933 | 0.929 |
| keyword only | 0.990 | 1.000 | 0.942 | 0.982 |
| hybrid, no prefilter | 0.974 | 1.000 | 0.981 | 0.929 |
| hybrid + prefilter | 0.990 | 1.000 | 0.981 | 0.929 |

Miss categories (hybrid + prefilter): {'d': 1}

<details><summary>Misses</summary>

- q023 [lay] (d) newest leaves are yellow-green while older ones are fine  expected=['rec_000006', 'rec_000001'] got=['rec_000005', 'rec_000006', 'rec_000011', 'rec_000012', 'rec_000013']
- q053 [oos] expected none, got weak: my dog chewed the pot and the saucer cracked
- q054 [oos] expected none, got weak: qzxv wplk jrmt
- q055 [oos] expected none, got weak: what is the capital of France
- q056 [oos] expected none, got weak: how do I sharpen garden shears

</details>

## 2026-10-02 — embedder `sentence-transformers/sentence-transformers/all-MiniLM-L6-v2`

56 queries (in-scope + out-of-scope), K=5, config: rrf_k=60, N_kw=20, N_vec=20, min_viable=3, vec_min_score=0.35

| config | recall@5 | hit@5 | MRR | coverage acc |
|---|---|---|---|---|
| vector only | 0.968 | 0.981 | 0.923 | 0.982 |
| keyword only | 0.990 | 1.000 | 0.942 | 0.982 |
| hybrid, no prefilter | 0.987 | 1.000 | 0.976 | 0.982 |
| hybrid + prefilter | 0.994 | 1.000 | 0.976 | 0.982 |

Miss categories (hybrid + prefilter): {'d': 1}

<details><summary>Misses</summary>

- q047 [filter] (d) yellow leaves and sticky residue on my pothos  expected=['rec_000016', 'rec_000017', 'rec_000014'] got=['rec_000016', 'rec_000017', 'rec_000015', 'rec_000018', 'rec_000012']
- q053 [oos] expected none, got weak: my dog chewed the pot and the saucer cracked

</details>

## Decision (2026-10-02)
Two off-the-shelf embedders compared on the same 56 queries (tables above). `all-MiniLM-L6-v2` is the default: best recall@5 (0.994 hybrid + prefilter) and best coverage accuracy (0.982). `bge-small-en-v1.5` ties on MRR but labels more out-of-scope queries `weak` instead of `none` (its cosine scores run higher for unrelated text), so its `vec_min_score` would need re-tuning. With either real embedder the metadata pre-filter now helps or ties, unlike with the `hash` stand-in. Remaining misses are listed above; no fine-tuning is justified by these numbers.
