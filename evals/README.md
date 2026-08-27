# Retrieval evaluation set

23 manually curated cases in [`retrieval.json`](retrieval.json): 20 questions
whose answer lives in a known episode, and 3 off-corpus questions that must
return insufficient evidence rather than the nearest vector.

Each case carries:

| Field | Meaning |
| --- | --- |
| `question` | asked exactly as a user would |
| `expected_sources` | episode directory names under `episodes/`; **any** one counts as a hit. Empty means no source should be returned |
| `topic` | grouping, for spotting a systematically weak area |
| `notes` | why this case was chosen, where it is not obvious |

Expected sources were taken from real episode titles in the corpus, not guessed
— e.g. the product-market fit case points at `todd-jackson`, whose episode is
titled *"A framework for finding product-market fit"*.

## What it is for

PRD section 3 sets a secondary metric of **retrieval relevance ≥ 80%**. This
set is the foundation for measuring it:

```
relevance = cases where an expected source appears in the retrieved chunks
            ÷ cases with expected sources
```

## Running it

```bash
python scripts/eval_retrieval.py            # summary
python scripts/eval_retrieval.py --verbose  # every case, with the misses
```

It exits non-zero only if an off-corpus question produced an answer — that is
the failure that matters. A changed hit rate is a number to look at, not a
build break.

## What has and has not been measured

Run against the full corpus (303 documents, 9,842 chunks) at top_k=8,
threshold 0.45:

| | |
| --- | --- |
| expected episode in top 8 | 11/20 |
| off-corpus refused | 3/3 |

**That 11/20 is not the PRD's relevance metric and must not be reported as
one.** It is a strict proxy: it asks whether one pre-chosen episode appears in
the top 8. Several "misses" returned defensibly relevant material from a
different episode — asking about Stripe's product craft returned David
Singleton, Stripe's CTO, while the case expected Jeff Weinstein. PRD section 3
measures *chunk* relevance, which needs a human judging pass that has not
happened.

What the run did establish, with numbers:

```
best-match distance, on-corpus  : 0.181 – 0.367   (median 0.272)
best-match distance, off-corpus : 0.488 – 0.524   (median 0.508)
```

The harness cannot print that off-corpus band: the retriever drops chunks past
the threshold, so an off-corpus question comes back with none. The band was
measured separately, with the threshold raised, and is what the threshold was
chosen from.

An empty band between 0.37 and 0.49 — which is where the 0.45 threshold came
from. At the original 0.62, **zero** off-corpus questions were refused.

## Running a single case by hand

```bash
cd backend
python -m app.retrieval.search "How should a startup think about finding product-market fit?"
```

## Extending it

Keep it small and hand-checked. A case is only useful if its
`expected_sources` were verified against the actual transcript — a wrong
expectation makes the metric worse, not better.
