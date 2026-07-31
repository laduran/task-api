# Task API stress test

Cycles through: create a task -> rename it -> toggle `finished` a random
number of times (2-10) -> delete it. One cycle per Collection Runner
iteration.

## Files

- `stress-test.postman_collection.json` - the 4 requests + chaining scripts
- `stress-test.postman_environment.json` - `base_url` and `session_cookie` variables

## Auth: this API has no API key

`/tasks*` requires a signed-in session (Google OAuth, see `backend/auth.py`).
There's no bearer token to drop into Postman - you have to borrow a real
browser session's cookie:

1. Open the deployed app in a browser and sign in with Google.
2. Open DevTools -> Application (Chrome) / Storage (Firefox) -> Cookies ->
   your app's origin.
3. Copy the value of the `session` cookie.
4. In Postman, open the `Task API Stress Test Env` environment and paste it
   into `session_cookie`. Set `base_url` to the deployed URL (no trailing
   slash).

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
real concurrent load. To generate actual concurrency, either:

- run several `newman run ...` processes at once (e.g. a `for i in $(seq 1 10); do npx newman run ... & done; wait`), or
- use Postman's built-in Performance testing (Run Collection -> Performance
  tab) which supports virtual users and ramp-up.

## A note on hitting the deployed instance

This points at whatever `base_url` you configure - be sure that's a
non-production / staging deployment, or one you're fine putting load on, since
sustained runs can rack up cloud costs or trip rate limits on a free-tier
service.
