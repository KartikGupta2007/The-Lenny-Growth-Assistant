"""Debug CLI for retrieval. Not part of the API.

    python -m app.retrieval.search "how do I think about product-market fit?"
"""

from __future__ import annotations

import argparse
import asyncio

from app.config import get_settings
from app.db.session import get_engine, get_sessionmaker
from app.logging_config import configure_logging
from app.retrieval import retrieve


async def run(query: str) -> None:
    settings = get_settings()
    async with get_sessionmaker()() as session:
        result = await retrieve(session, query, settings=settings)

    print(f'\nquery: "{result.query}"')
    print(f"sufficient: {result.sufficient}  ({len(result.chunks)} chunks)\n")
    for position, chunk in enumerate(result.chunks, start=1):
        print(f"  {position}. distance={chunk.distance:.4f}  {chunk.title[:60]}")
        print(f"     {chunk.guest} | {chunk.source_path}#{chunk.chunk_index}")
        print(f"     {chunk.content[:160].replace(chr(10), ' ')}...\n")
    if not result.sufficient:
        print("  insufficient evidence: too little relevant material to answer.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the transcript corpus.")
    parser.add_argument("query", help="the question to search for")
    args = parser.parse_args()

    configure_logging(get_settings())

    async def go() -> None:
        try:
            await run(args.query)
        finally:
            await get_engine().dispose()

    asyncio.run(go())


if __name__ == "__main__":
    main()
