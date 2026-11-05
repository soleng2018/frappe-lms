# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Course access from groups (spec 0009): a learner in an Authentik group named exactly like a course is enrolled in that course only, with no batch. With no course group a known learner keeps their certificate and progress but loses the lessons. Two course groups are refused with a clear page.
- `nile_auth.cleanup.clear_batch_courses` lists and removes the old batch course rows.
- `make tools CMD="verify deploy"` proves the LMS is reachable and safe over its public hostname. It checks the ping, the home page with its CSS and JS files, the socket.io endpoint, and that plain HTTP redirects to https. A missing redirect is a warning, never a failure. Each line says PASS, WARN or FAIL, names the URL or compose key, and never shows a secret (see spec 0007).
- `verify deploy` also reads `deploy/compose.yaml` and fails if a service publishes a port, if any service other than `frontend` has Traefik labels or the Traefik network, if the router rule does not name `${LMS_HOSTNAME}`, or if log rotation or the restart policy is missing.
- `make restart-test` restarts the long running services, kills `backend` and `frontend` hard, waits up to 180 seconds for every service to be healthy, and runs `verify deploy` again. It touches only the `nile-lms` project.
- A separate MCP user (`LMS_MCP_USER`) with its own key and secret (`LMS_MCP_API_KEY`, `LMS_MCP_API_SECRET`), so an AI agent can use the MCP endpoint at `/api/v2/mcp` without the tools key. It never holds System Manager. To rotate the key, edit both values in `.env` and run `make up`. `verify deploy` checks that the endpoint answers 401 without a key and works with it.
- The README explains the one time Always Use HTTPS step in Cloudflare and how to connect an AI agent over MCP.
- Tests for these checks: unit tests with a mock web server, tests for the `create-site` guards, and a live integration test against the running stack.
- Content sync: `make tools CMD=sync` builds the Nile Workshop course in the LMS from files in git. `content/course.yaml` holds the chapters, lessons (video, lab guide or quiz) and the quizzes with their multiple choice questions. `content/labs/*.md` holds the lab guides. Running it again updates the same records and creates no duplicates (see spec 0005).
- `make tools CMD="sync --check"` lists what would change, writes nothing, and exits 1 if anything differs. It also lists lessons added by hand in the Desk.
- The sync checks the content files first and reports every problem in one run, naming the file and the key, before it writes anything.
- When a request to the LMS fails, the sync stops and prints the record, the URL, the HTTP status and the reason, without a traceback and without any secret.
- Every existing batch gets the course added once, and student progress is recalculated when the course outline changes.
- Tests for the sync: unit tests with a fake LMS, and live integration tests that build a throwaway course and a throwaway student on the running site, then delete them.

### Changed
- `sync` creates courses unpublished and adds them to no batch. It warns when a title change needs a new Authentik group name, and refuses a duplicate title or one equal to the admin group.
- The keys `AUTHENTIK_STUDENT_GROUP_PREFIX` and `AUTHENTIK_STUDENT_GROUP_SUFFIX` are retired. Delete them from `.env`.
- Git wins over the LMS. If a synced record was edited in the Desk, `sync` prints `LMS has X, git has Y` and overwrites it. Run `--check` first to see those edits.
- Nothing is deleted. A lesson, chapter, quiz or question removed from git leaves the course outline and stays in the LMS, and the command names each one it detaches.
- The Authentik login now refuses a user whose email matches the MCP user, with the same generic "cannot use this login" page it shows for the service user.
- `create-site` stops with "must differ" before it writes any site setting when `LMS_MCP_USER` matches `LMS_SERVICE_USER`, ignoring upper and lower case.

### Fixed
- Rotating the MCP key now works when the MCP user has no stored secret. The new key and secret from `.env` are written instead of the run failing with a confusing error.
- `restart-test` no longer stops with a template error if a service has no healthcheck.
