# Verify: LMS running behind Traefik · spec 0007 · updated 2026-11-03
_Steps derived from spec 0007 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## UI / manual
- [x] In Cloudflare (SSL/TLS, Edge Certificates) turn on Always Use HTTPS, then run `verify deploy` again → the `http redirect` line changes from WARN to PASS   → AC-3
- [x] Open `http://<LMS_HOSTNAME>/` in a browser before the toggle → it loads (no redirect), and after the toggle it lands on `https://`   → AC-3
- [x] Open `https://<LMS_HOSTNAME>/` in a browser → the LMS page and its styles load, no console errors   → AC-1
- [ ] Reboot the host once in a quiet window → `make ps` shows every service healthy, and the result is noted in the README   → AC-6 (follow-up, not an AC)
- [x] Connect an MCP client to `https://<LMS_HOSTNAME>/api/v2/mcp` with `Authorization: token <key>:<secret>` → it initializes; without the header it gets 401   → AC-4
- [x] Try an Authentik login whose email equals `LMS_MCP_USER` → the generic "cannot use this login" page (403), and the MCP user record is unchanged   → AC-5

## Commands
- [x] `make tools CMD="verify deploy"` → one PASS/WARN/FAIL line per check, naming the URL or compose key, exit 0 when no FAIL   → AC-1, AC-8
- [x] `make tools CMD="verify deploy" | grep -c "$(grep ^LMS_MCP_API_SECRET= .env | cut -d= -f2)"` → 0 (no secret value in the output)   → AC-8
- [x] Remove the three `LMS_MCP_*` keys from a copy of `.env`, run `verify deploy` → one message naming all three at once, exit 1   → AC-8
- [x] `curl -s -o /dev/null -w '%{http_code}' -X POST https://<LMS_HOSTNAME>/api/v2/mcp` with the JSON-RPC initialize body and no key → 401 containing `Authentication`   → AC-4
- [x] Same request with the MCP user's token header → 200 with a JSON-RPC `result`   → AC-4
- [x] Add `ports: ["8000:8000"]` to a service in a copy of `deploy/compose.yaml`, run the unit tests → the static check fails   → AC-2
- [x] Remove `max-file` from one service's logging in a copy → the static check fails and names the service   → AC-7
- [x] `make up` twice with the same `.env` → `create-site` logs `MCP user ... already set up`   → AC-5
- [x] Change `LMS_MCP_API_KEY` and `LMS_MCP_API_SECRET` in `.env`, run `make up` → logs `key and secret updated`; `verify deploy` passes with the new key, and the old key gets 401   → AC-5
- [x] Set `LMS_MCP_USER` equal to `LMS_SERVICE_USER`, run `make up` → create-site stops with "must differ" and changes nothing   → AC-5
- [x] In the Desk, give the MCP user System Manager, run `make up` → create-site exits naming System Manager and changes nothing further   → AC-5
- [x] `make restart-test` → the long running services restart, `backend` and `frontend` are killed with `kill -9`, all are healthy within 180 s, live log and restart values match, `verify deploy` passes   → AC-6, AC-7
- [x] `docker ps` before and after `make restart-test` → no container outside the `nile-lms` project restarted   → AC-6
- [x] `cd tools && uv run pytest -m integration tests/test_verify_integration.py` → passes   → AC-1, AC-2, AC-4, AC-5, AC-7, AC-8

## Value sourcing (one step per row of the spec's table)
- [x] Base URL: change `LMS_HOSTNAME` in a copy of `.env` to a wrong host → every public check FAILs naming that URL (WARN for the HTTP redirect)   → AC-1, AC-3
- [x] Asset paths: serve a home page with no `/assets/` CSS or JS (unit test) → FAIL; with 8 assets → only the first 5 of each type are fetched   → AC-1
- [x] Network failure: block the host with a bad DNS name → each check names its URL, the redirect check is WARN, others FAIL   → AC-1, AC-3, AC-8
- [x] Keys needed: remove only `LMS_MCP_API_KEY` → message names it (and only the missing ones)   → AC-8
- [x] Compose facts: put a `${LMS_HOSTNAME}` rule on a second service via anchors/merge in a copy → the label check still catches it   → AC-2
- [x] MCP credentials header: run with a wrong secret → `mcp with key` FAILs and the output shows no secret value   → AC-4, AC-8
- [x] Expected log values and restart policy: set one long running service to `restart: "no"` in a copy → FAIL naming it   → AC-7
- [x] Which services are long running: add a service with `profiles` and one that others wait on with `service_completed_successfully` (unit test) → neither is treated as long running   → AC-6, AC-7
- [x] Running containers and their health: stop `queue-long` by hand (`docker stop`), run `make restart-test` → it fails naming `queue-long` as not running   → AC-6
- [x] Host PID to kill: confirm the printed PIDs match `docker inspect -f '{{.State.Pid}}'` for `backend` and `frontend`   → AC-6
- [x] MCP user rerun: delete the MCP user in the Desk, run `make up` → it is recreated; run again → no change   → AC-5
- [x] MCP user id, key, secret: run `docker inspect` on the `create-site` container → they appear only as environment variables, not in the command   → AC-5
- [x] Site config `nile_mcp_user`: `bench --site <host> show-config` (row `nile_mcp_user`) → equals `LMS_MCP_USER`   → AC-5
- [x] Health timeout and services to kill: read `TIMEOUT` and `KILL_SERVICES` in `restart-test.sh` → 180 and `backend frontend`   → AC-6

## Acceptance-criteria coverage
- AC-1 … public checks, browser step, integration test · AC-2 … compose unit tests, label/ports steps · AC-3 … Cloudflare steps, redirect unit tests · AC-4 … MCP curl steps, client step · AC-5 … rerun, rotation, System Manager, same-user, login steps · AC-6 … `make restart-test`, project scope step · AC-7 … logging and restart steps, `restart-test` · AC-8 … output, missing keys, secret grep steps
