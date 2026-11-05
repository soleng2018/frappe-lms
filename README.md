# Nile Workshop LMS

A Frappe LMS that certifies students for a hands on lab. It runs as Docker containers behind an existing Traefik, and students log in through Authentik. Scope: [docs/scope/scope.md](docs/scope/scope.md). Design: [docs/specs/](docs/specs/).

## 1. Prerequisites

You need all of these before you start.

| Need | Why |
|---|---|
| Linux host with Docker Engine and the Compose plugin (`docker compose`, a recent v2 release: the Makefile uses `run --quiet-build`, tested with v2.39.4), enabled at boot | Runs everything. Containers restart after a reboot only if Docker starts. |
| `make`, `git`, `curl`, `sha256sum` | The Makefile and the build scripts use them. |
| An existing Traefik v3 container on an external Docker network (default name `traefik`) with a `websecure` entrypoint and a `letsencrypt` certificate resolver | Routes HTTPS to the LMS. This repo does not start Traefik. |
| A public DNS name for the LMS (for example `guide.nile.global`) pointing at the host that runs Traefik | It becomes the Frappe site name and the Traefik host rule. It cannot change after the first start. |
| A running Authentik with admin access, holding the `HOL: OpenID groups scope` property mapping, the `default-provider-authorization-implicit-consent` flow and a self signed certificate | Students and admins log in through it. `idp setup` stops with a named error if one of these is missing, and never edits them. |
| Internet access during the first build | Pulls the base images and clones Frappe, LMS and payments at pinned tags. |
| `sudo` on the host and access to the Cloudflare dashboard of your zone | `make restart-test` kills container processes with `sudo kill -9`. The Cloudflare step in section 6 makes plain HTTP redirect to HTTPS. |
| `uv` and Python 3.12 (only if you run the `tools` code or tests on the host) | Lint and unit tests. Not needed to run the stack. |
| Docker, `uv` and `git` on any machine that commits | The commit hook runs hadolint and gitleaks in Docker, and ruff, mypy and pre-commit through `uv`. |

## 2. Secrets and settings you need

Everything lives in one file, `.env`, at the repo root. It is never committed and must be mode 0600, owned by you. `.env.sample` lists every key. It is generated from the key list in `tools/src/nile_tools/config.py`, so edit the list, not the sample (`make` and the tests tell you when they differ).

**Rules for a value:** only letters, digits and `_ . : / @ + = , -`. No quotes, spaces, `$`, `#` or backslash, because Docker Compose and the Python tools read these differently. A pasted token with other characters is rejected with its line number. Do not export these keys in your shell: the Makefile refuses to run if you do.

**You must supply these** (no generated value can replace them):

| Key | What it is |
|---|---|
| `LMS_HOSTNAME` | The public hostname of the LMS. Fixed after first start. |
| `AUTHENTIK_HOSTNAME` | The hostname of your Authentik. |
| `AUTHENTIK_API_TOKEN` | An Authentik API token that may create providers, applications and groups. |

**Generated for you** by `make init` the first time (it never overwrites a key that already has a value):

| Key | What it is |
|---|---|
| `LMS_ADMIN_PASSWORD` | Password of the Frappe `Administrator`. |
| `DB_ROOT_PASSWORD` | MariaDB root password. MariaDB ignores a change after the first start. |
| `LMS_ENCRYPTION_KEY` | Frappe `encryption_key`. It encrypts every password field, so a restore is impossible without it. Back it up. |
| `LMS_API_KEY`, `LMS_API_SECRET` | API credentials of the service user that the tools container uses. |
| `LMS_MCP_API_KEY`, `LMS_MCP_API_SECRET` | API credentials of a separate MCP user for your AI agent (section 6). Not fixed: to rotate, edit both in `.env`, then `make up`. |

**Defaults you may change:** `LMS_SERVICE_USER`, `LMS_MCP_USER` (default `nile-mcp@example.com`), `LMS_TIMEZONE` (default `America/Los_Angeles`, so Pacific time; use any IANA name), `AUTHENTIK_APP_SLUG`, `AUTHENTIK_ADMIN_GROUP`, `TRAEFIK_NETWORK`, `TRAEFIK_ENTRYPOINT`, `TRAEFIK_CERT_RESOLVER`.

**Fixed after the first start** (never edit once the stack has run): `LMS_HOSTNAME`, `LMS_ADMIN_PASSWORD`, `LMS_ENCRYPTION_KEY`, `LMS_SERVICE_USER`, `LMS_MCP_USER`, `LMS_API_KEY`, `LMS_API_SECRET`, `DB_ROOT_PASSWORD`, `AUTHENTIK_APP_SLUG`. **Keep a private copy of `.env`**: if you lose it, the data in the volumes cannot be recovered, and `create-site` refuses to start with a different encryption key.

Version pins are not secrets. They live in the committed `deploy/versions.env`.

## 3. Quick start

```bash
git clone <this repo> && cd <this repo>
make init          # creates .env and fills generated secrets
$EDITOR .env       # set LMS_HOSTNAME, AUTHENTIK_HOSTNAME, AUTHENTIK_API_TOKEN
make check         # lists every bad or missing key at once (make up runs it for you)
make up            # check, fetch upstream, build the image, start the stack
make ps            # every long running service should show (healthy)
make tools CMD=whoami   # proves the API path: prints the service user name
make hooks         # once per clone: installs the pre-commit hook (needed before you commit)
```

The first `make up` builds the image, which takes a while. `configurator` and `create-site` run once and exit 0. Then the long running services become healthy.

## 4. Commands

| Command | Does |
|---|---|
| `make init` | Create `.env` from the sample at mode 0600 and generate missing secrets. Run again after an update: it adds new keys and never changes a value you have. |
| `make check` | Check `.env` (syntax, values, mode, owner, not tracked by git, no secret in a tracked file). Prints every problem and no secret. |
| `make build` | Check, then fetch the pinned frappe_docker checkout and build the image. |
| `make up` | Check, build, then start the stack in the background. A bad key stops it before anything is built. |
| `make down` | Stop the stack. Volumes (database, site files) are kept. |
| `make ps` | Show all containers of the stack. |
| `make logs` | Last 100 log lines per service. |
| `make tools CMD=<command>` | Run a tools command in the tools container. Today: `init`, `whoami`, `content check [COURSE]`, `content new COURSE [--title TEXT]`, `sync [COURSE] [--check]`, `idp setup [--resync-secret]` (creates or fixes the Authentik application and the Frappe login key, then turns off Frappe's password form and email link and LMS guest access, so a signed out visitor sees no page data or site totals; safe to run again, prints `created`, `unchanged` or `fixed` per item, never a secret), `idp check [--user NAME]` (read only report of PASS, WARN or FAIL lines, exit 1 on any FAIL; `--user` is a real Authentik username, used to test that the groups claim comes out), `idp remove` (deletes only the Frappe key, provider and application that setup created, in that order; Frappe users and the password form are left as they are, so run `idp password-login on` afterwards to sign in as `Administrator`), `idp selftest` (the proof that sign in works: makes a throwaway Authentik student, a throwaway course and a group named like it, signs in through the real Authentik and LMS, checks the student lands on that course with the LMS Student role and only that enrollment, checks a second user in no course group gets the 403 page and no Frappe user, then removes everything it made; it also cleans leftovers of a killed run first, refuses to start if an item with a test name exists without our marker, prints PASS or FAIL per check and exits 1 on any FAIL; run `idp setup` first), `idp password-login on\|off` (break glass: `on` brings back the password form so `Administrator` can sign in while Authentik is down, `off` closes it again; `off` refuses unless the enabled Authentik key exists), `config check [--for up\|tools-authentik]`, `config show` (secrets as `*****`), `config sample`. |
| `make tools CMD="verify deploy"` | Prove the LMS over its public hostname: ping, home page, assets, socket.io, HTTP redirect, the MCP door, and the compose file (no published ports, log rotation, restart policy). One `PASS`, `WARN` or `FAIL` line per check. Exits 1 only on a FAIL. |
| `make restart-test` | Restart the long running services, `kill -9` the `backend` and `frontend` processes, and check everything is healthy again within 180 seconds, then run `verify deploy`. Needs Docker and `sudo` on the host. Touches only the `nile-lms` project. |
| `make hooks` | Install the pre-commit hook. Run once per clone. |
| `make lint` | Scan the tree for secrets with gitleaks (in Docker), then run every hook on all files (hygiene, shellcheck, shfmt, hadolint, ruff, mypy, compose check). Hooks fix what they can and fail the run when they changed a file, so run it again. |
| `make fmt` | Same as `make lint`. |
| `make test` | Unit tests in `tools/` with a coverage report. Integration tests are skipped. |
| `make compose-config` | Check that the compose file resolves with the committed pins and `.env.sample`. |

The stack tests need the stack running and a `.env`: run `cd tools && uv run pytest -m integration`. They rerun `create-site` against your live site, which keeps it and changes nothing except pending migrations.

Style: `tools/` uses spaces and 100 columns, `apps/nile_auth/` follows Frappe (tabs, 110 columns). Details in [spec 0003](docs/specs/0003-coding-standards-and-tooling.md).

### Signing in and break glass

After `idp setup`, the only way into the LMS is the Authentik button. Everyone lands on `/lms` after signing in (a safe deep link on this site is kept). If Authentik is down and you must get in as `Administrator`:

1. `make tools CMD="idp password-login on"` brings back the password form.
2. Sign in as `Administrator`.
3. `make tools CMD="idp password-login off"` closes it again. Running `idp setup` also closes it.

Changing the login landing code needs a new image: `make up` after the `nile_auth` version bump.

## 5. Course content

You write each course in git as one folder, and the `sync` command builds every course in the LMS. The full format, every field and every check message are in [docs/authoring.md](docs/authoring.md). `content check` and `content new` need no `.env`. `sync` needs the stack running and the service user's key and secret in `.env` (`LMS_HOSTNAME`, `LMS_API_KEY`, `LMS_API_SECRET`, all created by `make init` and `make up`). No new keys.

```bash
make tools CMD="content new my-course"    # a starter folder in content/my-course/ that already passes the check
make tools CMD="content check"            # every problem in every course, offline (add a course key for one)
make tools CMD="sync --check"             # lists what would change; changes nothing; exits 1 if anything differs
make tools CMD=sync                       # checks first, then makes the LMS match git for every course
make tools CMD="sync my-course"           # only that course
```

- A course is `content/<course-key>/` with `course.yaml`, markdown in `guides/`, one file per quiz in `quizzes/` and pictures in `images/`. A lesson is a list of blocks (text, video, quiz) in the order you want. A commit that touches `content/` runs `content check` and fails on any problem (`make hooks` once per clone).
- Every record has a `key`, and keys are unique across all courses. The key is how the sync finds the record, so you can rename a title freely, but changing a key makes a new record and detaches the old one. Keep keys as text. In YAML write `"no"` and `"yes"` in quotes, and write a video id as text.
- A course with a problem is skipped and listed at the end, and the other courses still sync. Every output line starts with `[<course-key>]`.
- Images in a guide are uploaded as public files with unguessable names. Do not put a secret in an image.

- Run it again after you edit git: it updates the same records and creates no duplicates. With nothing to change it says `[<course-key>] nothing to change`.
- Git wins. If someone edited a synced record in the LMS, `sync` prints `LMS has X, git has Y` and overwrites it. Use `--check` first to see those edits.
- Nothing is deleted. A lesson, chapter, quiz or question you remove from git leaves the course and stays in the LMS. The command names each one it detaches.
- If a request fails, that course stops, with the record, the URL, the status and the reason; the other courses carry on and the command exits 1. Run it again: it carries on where it stopped.
- The course is created and kept unpublished, and it is added to no batch. A learner reaches it only through an enrollment made at login. Progress is recalculated when the outline changes.
- If you change a course title, `sync` prints the old and new title first. The Authentik group name must change too. A course whose title another course already has, or that equals `AUTHENTIK_ADMIN_GROUP`, is blocked and listed.

### Passing and the certificate (spec 0010)

No new keys. The rules come from the LMS itself, and `sync` refuses a quiz whose `passing_percentage` is under 80 or over 100.

- **Pass mark.** A quiz passes at 80% or more. A score is stored as a whole number and cut down, never rounded up, so 79.5% is stored as 79 and fails.
- **Attempts.** Each quiz allows 3 attempts unless its content file sets `max_attempts`. After the last miss the LMS refuses another attempt.
- **Student: get the certificate.** Pass every quiz and finish every lesson (progress 100), then press the certificate button on the course page. **Do this while you are still in your course group.** When the group goes away you are removed from the course and the button is gone. A certificate you already hold stays. If someone misses the window, put them back in the group, let them sign in, and ask them to press the button.
- **Student: find it.** Open Profile, then Certificates. The download link holds the certificate name (the `name=` part). Your certificate is private until an admin publishes it.
- **Student: LinkedIn.** Ask a hol-admin to publish your certificate. Then add it under Licenses and certifications: name is the course title, organization is Nile, issue date is the certificate date, credential id is the certificate name, credential URL is `https://<LMS_HOSTNAME>/courses/<course name>/<certificate name>`. Publishing shows your name publicly, so it only happens on your request.
- **Admin: publish.** In the Desk open LMS Certificate, filter by member or course, open the certificate, tick Publish on Participant Page, save. Untick it to make it private again. A student cannot do this. Publishing or unpublishing works at any time, even after the learner has left the course group. The learner must still request the certificate while enrolled, because a person with no enrollment cannot create one.
- **Admin: reset a locked out student.** In the Desk open LMS Quiz Submission, filter by quiz and member, select that student's rows and delete them. The student can try again. Passed lessons and other progress stay. An admin needs the Moderator role.
- **Admin: see who is where.** In the Desk open the report **Learner Progress** (one row per learner and course) or **Quiz Scores** (one row per learner and quiz). Only Moderators and System Managers can open them, so `hol-admins` members can and students cannot. Status in Learner Progress is **Certified** (a certificate exists, published or not), **Ready for certificate** (every lesson done), **In progress** (at least one lesson done) or **Not started**. A learner whose slot has ended stays in the list with Enrolled set to No. A **Ready for certificate** learner with Enrolled No must be put back in the group before they can request the certificate. In Quiz Scores a **Locked** state is a link to that learner's attempts, where you can delete them to reset the quiz. The reports only read data and need no setup after `make up`.
- **Warning in the log.** If a login removes an enrollment at 100% progress and the learner has no certificate, `nile_auth` writes one `stranded learner` warning with the email and course. Search the `nile_auth` log for it.

Run the live proof from the repo with `cd tools && uv run pytest tests/test_pass_certificate_integration.py -m integration` (needs the stack up and `.env`).

## 6. Checking the deployment and connecting an agent

Run `make tools CMD="verify deploy"` after every rebuild.

**Always Use HTTPS (one time, in Cloudflare).** Cloudflare sends plain HTTP requests to Traefik over HTTPS, so Traefik never sees them and cannot redirect. In the Cloudflare dashboard open your zone, then SSL/TLS, then Edge Certificates, and turn on **Always Use HTTPS**. Run `verify deploy` again: the `http redirect` line changes from `WARN` to `PASS`.

**Connect an AI agent over MCP.** The LMS has a built in MCP endpoint at `https://<LMS_HOSTNAME>/api/v2/mcp`. Without a key it answers 401. `create-site` makes a separate user (`LMS_MCP_USER`) with the Desk User role and the four LMS roles, and never System Manager, so it cannot change settings, users or roles. Give your agent this header, with the values of `LMS_MCP_API_KEY` and `LMS_MCP_API_SECRET` from `.env`:

```
Authorization: token <LMS_MCP_API_KEY>:<LMS_MCP_API_SECRET>
```

The agent can read and write LMS content. Git is the source of truth, so an agent edit shows up as drift in `sync --check` and the next `sync` overwrites it. To revoke the agent, disable the user in the Desk, or change both keys in `.env` and run `make up`. The tools key is never used for the agent.

**Reboot test (once, by hand).** `restart-test` does not reboot the host. In a quiet window, reboot it and check `make ps` shows every service healthy. Other apps on the server go down too, so note the result here when you have done it.

## 7. Layout

- `deploy/`: compose file, image build, version pins, container scripts.
- `tools/`: Python package for setup scripts.
- `apps/nile_auth/`: custom Frappe app: Authentik groups become LMS access at login (`hol-admins` admin, a group named exactly like a course enrolls the learner in that course only).
- `content/<course-key>/`: courses (see [docs/authoring.md](docs/authoring.md)). `brand/`: brand assets (do not edit). `docs/`: scope, specs, reviews.

## 8. Keeping this file current

This README is updated at the end of every work turn that changes how the repo is set up or used. See the rules in [AGENTS.md](AGENTS.md).

## Upgrading from the batch based login (spec 0009)

1. Delete the lines `AUTHENTIK_STUDENT_GROUP_PREFIX` and `AUTHENTIK_STUDENT_GROUP_SUFFIX` from `.env`. Every command fails with a "retired" line until you do.
2. `make build` and `make up` (this takes the new `nile_auth` version).
3. `make tools CMD=sync` sets the existing course to unpublished.
4. Read, then run, the cleanup of the old batch course rows: `bench --site <site> execute nile_auth.cleanup.clear_batch_courses` (lists only), then add `--kwargs "{'dry_run': False}"` to remove them.
