# hibrid — local development

Two projects that run together:

- **`hibrid-engine/`** — the Python FastAPI engine (routine generation & variation)
- **`hibrid-app/`** — the TanStack Start / React mobile web client

## Run everything

```bash
./run.sh            # backend on :8000 + frontend dev server, Ctrl+C stops both
./run.sh backend    # only the engine API  (http://127.0.0.1:8000, docs at /docs)
./run.sh frontend   # only the web app     (Vite dev server, prints its port)
```

The first run creates the Python venv and installs both dependency sets
automatically. The frontend uses `bun` if installed, otherwise `npm`.

Env overrides: `API_PORT`, `API_HOST`, `VITE_API_URL`
(defaults to `http://127.0.0.1:8000`; see `hibrid-app/.env.example`).

## How they connect

The **Sessione** screen calls the engine:

| UI action | Endpoint | File |
|---|---|---|
| Generate / Rigenera a session | `POST /sessions/generate` | `hibrid-app/src/lib/engine-api.ts` |
| Re-roll one exercise (↻ / Shuffle) | `POST /sessions/blocks/vary` | same |

`engine-api.ts` maps the UI vocabulary onto the engine's enums
(sport → objective, effort → difficulty, Italian muscle groups → `Muscle`) and
adapts the engine's `SessionBlock` shape onto the frontend `Block`. Every call
**falls back to the local mock** (`fitness-data.buildSession`) when the backend
is unreachable, so the UI can still be iterated on offline — a small `engine` /
`offline` badge on the Sessione screen shows which source is live.
