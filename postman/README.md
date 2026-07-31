# Task API stress test

Mirrors the live collection in the Postman workspace (My Workspace >
PythonTODO > Stress Test folder). Cycles through: create a task -> rename it
-> toggle `finished` a random number of times (2-10) -> delete it. One cycle
per Collection Runner iteration.

This backup is a point-in-time export - if you edit the requests/scripts in
the Postman app, re-export to keep this in sync (see "Keeping this in sync"
below).

## Files

- `stress-test.postman_collection.json` - collection "PythonTODO" containing
  the "Stress Test" folder (4 requests + chaining scripts)
- `stress-test.postman_environment.json` - environment "PythonTODO Cloud
  Stress": `base_url` (currently `https://task-api-zv2i.onrender.com`) and
  `session_cookie` variables

## Auth: this API has no API key

`/tasks*` requires a signed-in session (Google OAuth, see `backend/auth.py`).
There's no bearer token to drop into Postman - you have to borrow a real
browser session's cookie:

1. Open the deployed app in a browser and sign in with Google.
2. Open DevTools -> Application (Chrome) / Storage (Firefox) -> Cookies ->
   your app's origin.
3. Copy the value of the `session` cookie.
4. In Postman, open the `PythonTODO Cloud Stress` environment and paste it
   into `session_cookie`. `base_url` is already set to the deployed URL.

This cookie is a signed value with no server-side session store, so it stays
valid independent of the browser tab it came from - it won't expire just
because you close the browser or log out elsewhere. It does stop working if
`SECRET_KEY` is rotated on the server or the user account is deleted.

## Running it

**Collection Runner (in-app):** open the collection, click Run, select the
environment, set Iterations to however many create/edit/toggle/delete cycles
you want. Each iteration always restarts at "1. Create Task" regardless of
the `setNextRequest` looping used internally for the toggle step.

**Newman (scripted / CI / heavier load):**

```bash
npx newman run postman/stress-test.postman_collection.json \
  -e postman/stress-test.postman_environment.json \
  -n 100 --delay-request 50
```

`-n` is the iteration count; `--delay-request` (ms) throttles how fast
requests fire.

**Real concurrent load:** a single Runner/Newman run executes iterations
sequentially, not in parallel - fine for a slow trickle of traffic, but not
real concurrent load. Use `run-parallel-load.sh`:

```bash
./postman/run-parallel-load.sh <workers> <iterations-per-worker> <delay-ms>
# e.g. 10 concurrent workers, 25 iterations each, 10ms delay between requests
./postman/run-parallel-load.sh 10 25 10
```

Each worker is a separate `newman` OS process with its own independent
in-memory collection variables, so there's no cross-worker race on
`task_id`/`toggle_count`/etc. Per-worker output goes to
`postman/run-logs/<timestamp>/worker-N.log` (gitignored).

We tried Postman's in-app Performance testing (Run -> Performance tab,
virtual users + duration) first, but it failed to start with a generic,
undiagnosable error ("Postman encountered an error... Please try again",
nothing logged to console) - possibly because virtual users there may not
share this collection's `pm.execution.setNextRequest` toggle-loop the way
Collection Runner does, or because its virtual users share variable state in
a way our collection-scoped variables don't handle safely under concurrency.
Parallel Newman sidesteps both problems entirely.

## A note on hitting the deployed instance

`task-api` runs on Render's free plan, which spins the instance down after
~15 minutes of no traffic. The first request after an idle gap can take
30-60+ seconds (cold start) and may time out - retry it once. Once the loop
is running continuously it keeps the instance awake on its own.

This points at whatever `base_url` you configure - be sure that's a
non-production / staging deployment, or one you're fine putting load on, since
sustained runs can rack up cloud costs or trip rate limits on a free-tier
service.

## Keeping this in sync

This JSON is exported from the live Postman collection, not the source of
truth - the Postman workspace is. If you edit requests or scripts in the app,
these files go stale silently (nothing enforces re-export). Either re-export
periodically, or switch to Postman's native "Connect Git" integration on the
collection to sync automatically instead of maintaining this by hand.
