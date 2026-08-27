#!/usr/bin/env python3
"""Export coding-agent transcripts to agent-transcripts/, with secrets redacted.

Claude Code stores each session as JSONL under ~/.claude/projects/<slug>/.
Those files contain real API keys and database URLs, so they are never copied
verbatim. This writes the conversation -- prompts and the agent's replies --
as Markdown, with every credential pattern replaced.

    python scripts/export_transcripts.py

Tool call payloads are summarised rather than included: they are the bulk of
the bytes and the least readable part. The prompts and replies are what show
the engineering decisions, the failed attempts and the corrections.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "agent-transcripts"
SESSIONS = (
    Path.home()
    / ".claude/projects"
    / "-Users-kartikgupta-Desktop-Self-Self-Made-Projects-The-Lenny-Growth-Assistant"
)

# Credential patterns. Each replacement is deliberately shaped so it cannot
# match its own pattern -- otherwise the check below flags the redaction itself
# as a leak. These four are asserted after writing.
CREDENTIALS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"), "sk-ant-<redacted>"),
    (re.compile(r"npg_[A-Za-z0-9]{8,}"), "npg_<redacted>"),
    (re.compile(r"ep-[a-z0-9-]+\.[a-z0-9-]*\.?[a-z0-9-]*\.aws\.neon\.tech"), "<redacted>.neon.tech"),
    # No colon in the replacement, so the user:password shape cannot recur.
    (re.compile(r"(postgresql(?:\+\w+)?://)[^:\s/@]+:[^@\s]+@"), r"\1REDACTED@"),
]

# Sanitised but not asserted: "KEY=REDACTED" still matches "KEY=\S+", so these
# cannot be used as leak assertions.
REDACTIONS = CREDENTIALS + [
    (re.compile(r"(ANTHROPIC_API_KEY\s*=\s*)\S+"), r"\1REDACTED"),
    (re.compile(r"(DATABASE_URL\s*=\s*)\S+"), r"\1REDACTED"),
    # Local paths carry the machine's username; not secret, but not useful.
    (re.compile(r"/Users/[A-Za-z0-9._-]+"), "~"),
]

MAX_BLOCK_CHARS = 6000

# Wrappers the harness injects into the message stream. They are not anything a
# person typed, so they are stripped; a message that is only a wrapper is
# dropped entirely.
INJECTED = [
    re.compile(r"<ide_opened_file>.*?</ide_opened_file>", re.S),
    re.compile(r"<ide_selection>.*?</ide_selection>", re.S),
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(r"<task-notification>.*?</task-notification>", re.S),
    re.compile(r"<command-(name|message|args)>.*?</command-\1>", re.S),
    re.compile(r"<local-command-[a-z-]+>.*?</local-command-[a-z-]+>", re.S),
]


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def strip_injected(text: str) -> str:
    for pattern in INJECTED:
        text = pattern.sub("", text)
    return text.strip()


def blocks(content: object) -> list[str]:
    """Readable text from a message.

    Tool calls become a marker so the reader can see where work happened; tool
    results are dropped -- they are the bulk of the bytes and add nothing once
    the call is already noted.
    """
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    out = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "text" and part.get("text", "").strip():
            out.append(part["text"])
        elif kind == "tool_use":
            out.append(f"\0{part.get('name', 'tool')}")
    return out


def export(path: Path) -> tuple[Path, int, int] | None:
    turns: list[str] = []
    pending: list[str] = []
    real = 0
    tools = 0

    def flush_tools() -> None:
        """One line for a run of tool calls, rather than one line each."""
        if not pending:
            return
        names = sorted(set(pending))
        shown = ", ".join(names[:4]) + ("…" if len(names) > 4 else "")
        turns.append(f"_[{len(pending)} tool call{'s' if len(pending) > 1 else ''}: {shown}]_")
        pending.clear()

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        for text in blocks(message.get("content")):
            if text.startswith("\0"):
                pending.append(text[1:])
                tools += 1
                continue
            text = strip_injected(text)
            if not text:
                continue
            flush_tools()
            if len(text) > MAX_BLOCK_CHARS:
                text = text[:MAX_BLOCK_CHARS] + "\n\n_[…truncated]_"
            turns.append(f"### {role.capitalize()}\n\n{text}")
            real += 1
    flush_tools()

    if real == 0:
        return None

    body = redact("\n\n".join(turns))
    target = OUT / f"{path.stem}.md"
    target.write_text(
        f"# Agent transcript — session `{path.stem}`\n\n"
        f"{real} prompts and replies, {tools} tool calls. Exported by "
        "`scripts/export_transcripts.py`. Credentials are redacted; tool "
        "payloads are omitted for readability.\n\n---\n\n" + body,
        encoding="utf-8",
    )
    return target, real, tools


def main() -> None:
    if not SESSIONS.is_dir():
        sys.exit(f"No session directory at {SESSIONS}")
    OUT.mkdir(exist_ok=True)

    total_turns = 0
    for path in sorted(SESSIONS.glob("*.jsonl")):
        result = export(path)
        if result is None:
            print(f"  {path.stem}: no prompts or replies, skipped")
            continue
        target, turns, tools = result
        total_turns += turns
        print(
            f"  {target.name}  {turns} turns, {tools} tool calls  "
            f"{target.stat().st_size // 1024} KB"
        )
    print(f"  {total_turns} turns exported in total")

    # Nothing leaves this script unredacted.
    leaked = []
    for written in OUT.glob("*.md"):
        if written.name == "README.md":
            continue  # documents the patterns, so it contains them by design
        text = written.read_text(encoding="utf-8")
        for pattern, _ in CREDENTIALS:
            if pattern.search(text):
                leaked.append(f"{written.name}: {pattern.pattern}")
    if leaked:
        sys.exit("REDACTION FAILED:\n" + "\n".join(leaked))
    print("  redaction verified: no credential patterns remain")


if __name__ == "__main__":
    main()
