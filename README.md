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
├── Dockerfile          multi-stage: node builds the bundle, python serves
├── .dockerignore
├── docker-entrypoint.sh
├── docker-compose.yml  Postgres + the API
├── backend/            Flask API
│   ├── app.py            application factory, OpenAPI config
│   ├── views.py          routes (the Blueprint the spec is generated from)
│   ├── schemas.py        marshmallow schemas
│   ├── models.py         SQLAlchemy models
│   ├── db.py             engine + per-request session
│   ├── alembic/          migrations
│   ├── gunicorn.conf.py  production server settings
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

### Database

Postgres runs in a container; nothing needs to be installed on the host
(`psycopg[binary]` bundles libpq).

```bash
docker compose up -d       # starts Postgres on 127.0.0.1:5432
docker compose ps          # wait for "healthy"
```

### Backend

```bash
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cd backend && .venv/bin/alembic upgrade head    # create the schema
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

## Running in a container

The whole stack, built and wired together:

```bash
docker compose up -d --build
```

That serves the same URLs on <http://127.0.0.1:8000>. The image is
multi-stage — Node builds the TypeScript bundle in the first stage and never
reaches the runtime image, which is Python only. `npm run build` typechecks
before bundling, so a type error fails the image build.

The entrypoint runs `alembic upgrade head` before starting gunicorn, so a
deploy migrates itself. Set `RUN_MIGRATIONS=0` to skip that if you'd rather
run migrations as a separate release step (worth doing once you run more than
a couple of replicas).

Everything is environment-driven, so the same image runs unchanged locally and
on a platform:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | local compose db | connection string |
| `PORT` | `8000` | port gunicorn binds |
| `WEB_CONCURRENCY` | `4` | gunicorn worker count |
| `RUN_MIGRATIONS` | `1` | run `alembic upgrade head` on start |
| `GUNICORN_TIMEOUT` | `30` | seconds before a wedged worker is killed |

### Health checks

| Endpoint | Checks | Use for |
| --- | --- | --- |
| `/healthz` | process is up; **no** database access | liveness probe |
| `/readyz` | `SELECT 1` against Postgres | readiness probe |

They are deliberately separate. A liveness probe that touched the database
would have the orchestrator restart every container during a brief Postgres
outage, turning a blip into a restart storm. Readiness failing just removes
the container from the load balancer, which is the correct response.

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

### Migrations

```bash
cd backend
.venv/bin/alembic revision --autogenerate -m "what changed"
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1      # undo the last one
```

The connection string comes from `DATABASE_URL` and is never committed;
`alembic.ini` deliberately leaves `sqlalchemy.url` blank and `env.py` falls
back to the environment. The default is the local compose database.

Tests run against a **separate** `taskapi_test` database (override with
`TEST_DATABASE_URL`) and apply the real migrations rather than
`create_all`, so a broken migration fails the suite instead of reaching
production. Create it once with:

```bash
docker compose exec db createdb -U taskapi taskapi_test
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

Tasks are stored in Postgres. `GET /tasks` orders by `id` explicitly —
Postgres guarantees no row order without `ORDER BY`, and an `UPDATE` can
relocate a row.

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
