# Agent transcripts

Coding-agent sessions from building this project, as required by the
assignment. Seven sessions, exported from Claude Code's own session logs —
**756 prompts and replies** in total.

| File | Turns | Tool calls | What it covers |
| --- | --- | --- | --- |
| `ab875f92-…md` | 336 | 592 | Final production hardening, the assignment audit, and the UI/UX redesign |
| `c25978e2-…md` | 278 | 470 | The main build: schema, ingestion, embeddings, retrieval, RAG, sessions, chat UI, artifacts |
| `79e0301b-…md` | 98 | 146 | Planning from the assignment brief: PRD, architecture and design documents |
| `593e10fb-…md` | 23 | 65 | Codebase review and the model-provider layer |
| `2446708e-…md` | 7 | 41 | Diagnosing a stale duplicate checkout serving port 5173 |
| `c32289d7-…md` | 7 | 19 | Short codebase walkthrough |
| `d177325a-…md` | 7 | 19 | Short codebase walkthrough |

"Turns" counts prompts and replies only. Tool calls are noted inline where they
happened — `_[13 tool calls: Bash]_` — but their payloads are not included.

## How these were produced

```bash
python scripts/export_transcripts.py
```

Claude Code stores sessions as JSONL under `~/.claude/projects/`. Those raw
files contain **live API keys and database URLs**, so they are never copied
verbatim. The exporter writes prompts and replies as Markdown and replaces
every credential pattern — Anthropic keys, Neon passwords and hostnames,
`postgresql://user:password@…` URLs, and local home paths. It re-reads what it
wrote and exits non-zero if any pattern survives.

Two things are dropped as noise rather than content: tool result payloads
(most of the bytes, none of the reasoning) and harness-injected wrappers such
as `<ide_opened_file>` and `<system-reminder>`, which nobody typed.

## Failed attempts and corrections

The assignment asks for these specifically, and they are in the transcripts.
Some of the more instructive ones:

- **`RETRIEVAL_MAX_DISTANCE` was measurably wrong.** The initial 0.62 refused
  **0 of 3** off-corpus questions — with ~10k chunks something is always within
  0.62, so insufficient-evidence was unreachable. Measured the distance
  distributions, found a clean gap (on-corpus 0.18–0.37, off-corpus
  0.49–0.52), moved it to 0.45.
- **A JSONB column that stored two kinds of "empty".** SQLAlchemy writes Python
  `None` into JSON columns as JSON `'null'`, not SQL `NULL`. All tests passed;
  a direct database query found it. Fixed with `none_as_null=True` plus the
  test that would have caught it.
- **`sync_database_url` was broken for Neon.** It only rewrote `+asyncpg`, so a
  bare `postgresql://` DSN resolved to psycopg2 — not installed. Alembic could
  never have run.
- **A security check that silently never fired.** The frontend boundary
  script's regex comment-stripper treated the `//` in `https://` as a line
  comment, so the absolute-URL rule was dead. Found by deliberately planting
  violations; replaced with a quote-aware scanner.
- **`/health` permanently reported `degraded`.** A 3s probe timeout was
  calibrated for localhost; Neon connections take ~6.5s, and the cancel killed
  the connection before it could be pooled, so every later probe failed too.
- **Verifying the wrong application.** Port 5173 was being served by a stale
  copy of this project elsewhere on the machine, so browser checks were running
  against a Phase-1 build.
- **The dev server bound IPv6 only.** `http://127.0.0.1:5173` was refused and
  Vite silently fell back to port 5174 when 5173 was busy, so the documented
  URL pointed at nothing. Found during UI verification, not by testing.
- **A redaction check that flagged its own output.** The exporter replaced Neon
  passwords with `npg_REDACTED`, which matches the very pattern it asserts
  against. The replacements are now shaped so they cannot self-match.
- **Test-harness races mistaken for bugs.** Several browser checks failed on
  fixed waits that fired before Neon round-trips completed. Each was
  investigated rather than assumed, and the harness was fixed — not the app.
