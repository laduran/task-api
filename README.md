# Task API

A small CRUD task API with a TypeScript + Alpine.js front end, built to compare
lightweight hypermedia-style front ends against heavyweight SPA frameworks.

- **Backend** — Flask + flask-smorest. The OpenAPI document is *derived* from
  marshmallow schemas and Blueprint routes, never hand-written, so it cannot
  drift from the implementation.
- **Frontend** — TypeScript compiled to a single bundle by esbuild, with
  Alpine.js for reactivity. No framework, no virtual DOM, no build-time
  templating.

## Layout

```
exercise1/
├── README.md
├── backend/            Flask API
│   ├── app.py            routes, schemas, OpenAPI config
│   ├── openapi.json      generated — do not edit by hand
│   ├── requirements.txt
│   └── tests/
├── frontend/           TypeScript sources
│   ├── src/
│   │   ├── main.ts       registers the component, starts Alpine
│   │   ├── taskApp.ts    the Alpine component
│   │   ├── api.ts        typed HTTP client + error decoding
│   │   └── types.ts      shapes mirroring openapi.json
│   ├── package.json
│   └── tsconfig.json
└── static/             served by Flask
    ├── index.html        markup only, no inline JS
    └── js/app.js         build output (gitignored)
```

`static/` is the handoff point between the two halves: the frontend build
writes into it, the backend serves from it.

## Build and run

### Backend

```bash
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

### Frontend

```bash
cd frontend
npm install
npm run build          # typechecks, then bundles to ../static/js/app.js
```

The bundle is not committed, so **the frontend must be built at least once**
or the page will load without behaviour.

### Run

```bash
cd backend
.venv/bin/python app.py
```

| URL | What |
| --- | --- |
| <http://127.0.0.1:5000/> | the demo front end |
| <http://127.0.0.1:5000/docs> | Swagger UI |
| <http://127.0.0.1:5000/openapi.json> | the generated spec |

## Development

```bash
cd frontend && npm run dev        # esbuild watch mode; reload the page to pick up changes
cd frontend && npm run typecheck  # tsc --noEmit, no bundling
cd backend  && .venv/bin/python -m pytest tests/ -q
```

Regenerate the spec after changing any route or schema — a test fails if the
committed copy is stale:

```bash
cd backend && .venv/bin/python app.py --dump-openapi
```

## The API

Base URL `/`. Every response is JSON, including errors.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/tasks` | list all tasks |
| `POST` | `/tasks` | create a task — `{"title": "..."}` |
| `GET` | `/tasks/{id}` | fetch one task |
| `PUT` | `/tasks/{id}` | update title and/or finished state |
| `DELETE` | `/tasks/{id}` | delete a task |

A task is `{"id": 1, "title": "Buy milk", "finished": false}`.

`PUT` applies a partial update but requires at least one of `title` or
`finished`; a body-less request is rejected rather than silently succeeding.

Errors use flask-smorest's standard shape. Validation failures return **422**
with per-field detail:

```json
{
  "code": 422,
  "status": "Unprocessable Entity",
  "errors": { "json": { "title": ["Title must not be blank."] } }
}
```

Tasks are held in memory, so **all state is lost when the server restarts**.

## Notes

The test suite covers the API's behaviour and guards the spec against drift:
every route must appear in the document, every documented path must be routed,
every operation needs an `operationId`, every error response needs a body, the
document must validate as OpenAPI 3.0.3, and the committed `openapi.json` must
match what the app generates.

flask-smorest only sees routes registered on a Blueprint, so a bare
`@app.route` would be invisible to the generator. That is the one remaining
drift vector, and `test_every_route_is_documented` catches it — pages that are
deliberately undocumented (`/`, static assets, the docs endpoints) are listed
in `UNDOCUMENTED_ENDPOINTS`.
