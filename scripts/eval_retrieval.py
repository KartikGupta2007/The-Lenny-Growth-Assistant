"""Score the retrieval evaluation set against the live corpus.

    python scripts/eval_retrieval.py            # summary
    python scripts/eval_retrieval.py --verbose  # per-case detail

Reports two things the PRD cares about separately:

  hit rate   -- an expected episode appears in the retrieved chunks. A strict
                proxy: it demands one pre-chosen episode, so a genuinely good
                answer sourced from a different episode scores as a miss.
  refusals   -- off-corpus questions correctly reported insufficient evidence.

Neither is a substitute for the PRD's chunk-level relevance metric, which
needs a human judging pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.retrieval import retrieve  # noqa: E402

CASES = ROOT / "evals" / "retrieval.json"


async def main(verbose: bool) -> int:
    cases = json.loads(CASES.read_text())["cases"]
    settings = get_settings()

    on_corpus, off_corpus = [], []
    async with get_sessionmaker()() as session:
        for case in cases:
            result = await retrieve(session, case["question"], settings=settings)
            best = min((c.distance for c in result.chunks), default=None)
            # source_path looks like episodes/<slug>/....
            found = {c.source_path.split("/")[1] for c in result.chunks if "/" in c.source_path}
            expected = set(case["expected_sources"])
            row = {
                "question": case["question"],
                "topic": case["topic"],
                "expected": expected,
                "found": found,
                "hit": bool(expected & found),
                "sufficient": result.sufficient,
                "best": best,
            }
            (on_corpus if expected else off_corpus).append(row)
            if verbose:
                mark = "hit " if row["hit"] else ("ok  " if not expected and not result.sufficient else "miss")
                if not expected:
                    mark = "ok  " if not result.sufficient else "LEAK"
                print(f"  {mark} d={best if best is None else round(best, 3)}  {case['question'][:62]}")
                if expected and not row["hit"]:
                    print(f"       expected {sorted(expected)}, got {sorted(found)[:3]}")

    hits = sum(r["hit"] for r in on_corpus)
    refused = sum(not r["sufficient"] for r in off_corpus)
    on_d = [r["best"] for r in on_corpus if r["best"] is not None]
    off_d = [r["best"] for r in off_corpus if r["best"] is not None]

    print(f"\n  top_k={settings.retrieval_top_k}  "
          f"max_distance={settings.retrieval_max_distance}  "
          f"min_chunks={settings.retrieval_min_chunks}")
    print(f"  expected episode retrieved : {hits}/{len(on_corpus)} "
          f"({hits / len(on_corpus):.0%})   [strict proxy, not the PRD metric]")
    print(f"  off-corpus refused         : {refused}/{len(off_corpus)}")
    if on_d:
        print(f"  best distance, on-corpus   : {min(on_d):.3f} - {max(on_d):.3f} "
              f"(median {statistics.median(on_d):.3f})")
    if off_d:
        print(f"  best distance, off-corpus  : {min(off_d):.3f} - {max(off_d):.3f} "
              f"(median {statistics.median(off_d):.3f})")

    # The only hard failure: an off-corpus question that produced an answer.
    return 1 if refused < len(off_corpus) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print every case")
    args = parser.parse_args()

    async def go() -> int:
        try:
            return await main(args.verbose)
        finally:
            await get_engine().dispose()

    raise SystemExit(asyncio.run(go()))
