# Running anything in data-pipeline/

**Use `.venv`, not the system Python.**

```
.venv/Scripts/python.exe sync_moves.py        # Windows
.venv/bin/python sync_moves.py                # macOS/Linux
```

Plain `python sync_moves.py` fails on this machine with:

```
ImportError: cannot import name 'TypeAdapter' from 'pydantic'
```

The system Python at `D:\Python` is shared with other projects, and one of them installed
`gradio 3.41.2` + `fastapi 0.94.0`, which pin `pydantic` to 1.10 and `httpx` to 0.24.
`supabase 2.31` needs pydantic 2.11+, so every script in this directory stops importing.
Nothing to do with this project, and not worth fixing by upgrading the shared environment
out from under whatever needs those old versions.

If the venv is missing or stale:

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

It is gitignored, so it does not exist on a fresh clone.

## Two dependencies that only matter locally

- **tzdata** — `zoneinfo` ships no timezone database on Windows, so anything using
  `ZoneInfo` (`notify_news`, `notify_games`, `generate_briefing`) dies with
  `ZoneInfoNotFoundError`. Ubuntu runners have it system-wide, which is why CI never
  caught this.
- **psycopg2-binary** — `migrate.py` only, which talks to Postgres directly because
  `CREATE TABLE` has no PostgREST equivalent. No workflow runs it.

CI installs from `requirements.txt` on every run, so the cloud pipeline is unaffected by
any of this. A local import error does **not** mean production is broken — check the
Actions run history before assuming it is.
