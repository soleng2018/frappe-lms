# Scope: Nile Workshop LMS

A Frappe LMS that certifies students for a hands on lab: they watch a video, follow a lab guide, pass a quiz for each at 80% or higher, and get a certificate. Managers (the `hol-admins` group) track progress and pull a monthly report. Everything is set up by script and runs as Docker containers behind the existing Traefik on this dev server.

**Build approach:** Tracer Bullet (prove the whole pipe works with one real thin path, then thicken one strand at a time).
**Workflow:** GA (after `/develop`: `/check verify`, then `/test`, then a fresh model `/check review`, then `/document`). The project default level of rigor. `/architect` is the recommended first stop for a feature with a real decision, but skippable when you already know the build. Any feature can carry its own tag (e.g. `· Beta`) to do more or less.

_These are recommendations to keep your build orderly, not requirements. Skip anything that does not fit: if you already know how to build a feature, use `/develop` and skip `/architect`. You decide when a feature is `done`._

## Source material

Read these before designing any feature. They are the original brief, not summaries.
- Requirements and instructions: [requirements.md](../../requirements.md). Its Instructions hold hard limits: this Frappe install is dev, only delete containers and Authentik items you created, and the group `hol-admins` already exists.
- Logos and design system: [brand/](../../brand/) (pulled from github.com/soleng2018/reservations). Used by Branding & theme (#10) and, if revived from Deferred, Outbound email (for the email logo).
- Sample compose file for Traefik labels: `/home/nova/lms/docker-compose.yaml` (it runs a different app).
- Frappe LMS repo: https://github.com/frappe/lms
- Frappe LMS docs: https://docs.frappe.io/learning/get-started/installation
- Frappe framework API: https://docs.frappe.io/framework/user/en/introduction

_The Frappe links have not been read by `/scope`; `/architect` should read the ones its feature needs._

## At a glance

| # | Feature | Phase | Status |
|---|---------|-------|--------|
| 1 | Stack & architecture | Foundation | done |
| 2 | Coding standards & tooling | Foundation | done |
| 3 | Single config & secrets file | Foundation | done |
| 4 | Data model (course, quiz, certificate, roles) | Foundation | done |
| 5 | LMS running behind Traefik | Slice 1 | done |
| 6 | IDP login (OIDC) | Slice 1 | done |
| 7 | Group to role mapping | Slice 1 | done |
| 8 | Content sync, one course | Slice 1 | done |
| 9 | Quiz pass rules & certificate | Slice 1 | done |
| 10 | Branding & theme | Slice 2 | done |
| 11 | Guide format & full authoring | Slice 2 | done |
| 12 | Manager progress view | Slice 3 | done |
| 13 | Monthly report | Slice 3 | in-progress |
| 14 | Backup & restore | Slice 4 | planned |
| 15 | Outbound email | Slice 4 | dropped |
| 16 | Health checks & error monitoring | Slice 4 | planned |
| 17 | Course access from course groups | Slice 1 | done |

## Foundations

### 1. Stack & architecture
Decide how Frappe LMS is run in containers, what language the setup script uses, and how it talks to the Frappe and IDP APIs. Then scaffold a runnable skeleton so every slice builds on real structure.
**Done when:** the stack is recorded in a spec, and the scaffold builds and starts as a container on this server.
spec [0001](../specs/0001-stack-and-architecture/index.md) · code in `deploy/`, `tools/`, `apps/nile_auth/`
- [x] Decide the stack (spec): `/architect stack & architecture`
- [x] Scaffold from the decision: `/develop stack & architecture`
- [x] Verify it: `/check verify stack & architecture`
- [x] Test it: `/test stack & architecture`
- [x] Review it (fresh model): `/check review stack & architecture`
- [x] Document it: `/document stack & architecture`

### 2. Coding standards & tooling
Capture conventions, then install lint, format, and checks from the real scaffolded project.
**Done when:** root `AGENTS.md` reflects the real stack, and lint and format run clean.
spec [0003](../specs/0003-coding-standards-and-tooling.md) · code in `.pre-commit-config.yaml`, `Makefile`, `tools/pyproject.toml`, `apps/nile_auth/pyproject.toml`
- [x] Design it (spec): `/architect coding standards & tooling`
- [x] Capture conventions and tooling choices: `/audit`
- [x] Install the tooling: `/develop tooling`
- [x] Check it runs clean: `/test`

### 3. Single config & secrets file
One file holds every parameter and secret: master API tokens, app URL, IDP details, backup settings. Nothing sensitive is hardcoded anywhere else.
**Done when:** every script and container reads its settings from this one file, a sample file lists each key, and the real file is kept out of git.
spec [0002](../specs/0002-single-config-and-secrets-file.md) · code in `tools/src/nile_tools/`, `Makefile`, `.env.sample`
- [x] Design it (spec): `/architect single config & secrets file`
- [x] Build it: `/develop single config & secrets file`
  - [x] Config module: key list, strict parser, validators, masking (AC-5, AC-7)
  - [x] Thin thread: `init`, sample, Makefile wrapper, `db` and `frontend` wiring (AC-1, AC-3, AC-6)
  - [x] Full key inventory, `versions.env`, delivery to all services, `create-site` wiring and mismatch guards (AC-3, AC-6, AC-8, AC-9)
  - [x] `config check`, git and secret scan, drift and parity tests (AC-2, AC-4, AC-5)
- [x] Verify it: `/check verify single config & secrets file`
- [x] Test it: `/test single config & secrets file`
- [x] Review it (fresh model): `/check review single config & secrets file`
- [x] Document it: `/document single config & secrets file`

### 4. Data model (course, quiz, certificate, roles)
Decide how courses, chapters, lessons, quizzes, attempts, and certificates map onto Frappe, and which Frappe roles the two IDP groups become.
**Done when:** the mapping is written down and covers everything slices 1 to 3 need without a rework.
spec [0004](../specs/0004-data-model/index.md) · code in `apps/nile_auth/`, `tools/src/nile_tools/`
- [x] Design it (spec): `/architect data model`
- [x] Build it: `/develop data model`
  - [x] Custom fields (`nile_key`, `nile_group`) and the Moderator delete permission fixture in `nile_auth` (AC-3, AC-4, AC-6)
  - [x] Content model and pure content check in `tools` (AC-1, AC-2, AC-8)
  - [x] Compare function for drift between git and the LMS (AC-9)
  - [x] Model constants for roles, user types, and batch defaults in `nile_auth` (AC-4)
  - [x] Live site integration test and recorded LMS names, once feature 5 is up (AC-2, AC-5, AC-6, AC-7)
- [x] Rebuild for the body macros: `/develop data model`
  - [x] `lesson_body` function and the video id check in `tools`, with unit tests (AC-8, AC-10)
  - [x] Compare reports quiz and video lessons whose body is not the macro, and the live test also tries a lesson with the macro (AC-9, AC-10)
- [x] Verify it: `/check verify data model`
- [x] Test it: `/test data model`
- [x] Review it (fresh model): `/check review data model`
- [x] Document it: `/document data model`

## Slice 1: the thin certify thread

### 5. LMS running behind Traefik
Frappe LMS starts as Docker containers from one compose file, with Traefik labels for the app URL, following the sample in `/home/nova/lms`.
**Done when:** the LMS opens over HTTPS at its hostname, survives a restart, and logs rotate.
spec [0007](../specs/0007-lms-behind-traefik/index.md) · code in `tools/src/nile_tools/`, `deploy/scripts/`, `apps/nile_auth/`
- [x] Design it (spec): `/architect LMS running behind Traefik`
- [x] Build it: `/develop LMS running behind Traefik`
  - [x] Thin thread: `verify deploy` with the ping check, then the public, HTTP redirect and compose checks (AC-1, AC-2, AC-3, AC-7, AC-8)
  - [x] Dedicated MCP user: config keys, `create-site`, `ensure_mcp_user`, login protection, and the MCP checks (AC-4, AC-5)
  - [x] `restart-test` script and Makefile target (AC-6, AC-7)
  - [x] Live integration test, README, and the Cloudflare Always Use HTTPS step (AC-1 to AC-8)
- [x] Verify it: `/check verify LMS running behind Traefik`
- [x] Test it: `/test LMS running behind Traefik`
- [x] Review it (fresh model): `/check review LMS running behind Traefik`
- [x] Document it: `/document LMS running behind Traefik`

### 6. IDP login (OIDC) · done
A script creates the OIDC application in Authentik through its API (only items it creates), and configures Frappe through its API to sign users in with it. Students and teachers log in only this way.
**Done when:** running the script on a clean setup lets a student sign in through Authentik and land in the LMS, and running it twice changes nothing.
spec [0008](../specs/0008-idp-login/index.md) · code in `tools/src/nile_tools/`, `apps/nile_auth/`
- [x] Design it (spec): `/architect IDP login`
- [x] Build it: `/develop IDP login`
  - [x] Probe the live Authentik and Frappe, then the thin thread: `idp setup` creates the provider, application, and Frappe key (AC-1, AC-4, AC-6)
  - [x] Safe reruns: marker, diff and fix in place, secret rule, pre checks, retry and errors (AC-2, AC-4, AC-9)
  - [x] Close the bypasses: password form and email link off, `idp password-login on|off` (AC-5)
  - [x] `idp check` and `idp remove` (AC-7, AC-8)
  - [x] Landing on `/lms`, `idp selftest`, the manual admin sign in, and README with the break glass steps (AC-3, AC-10, AC-11, AC-12)
- [x] Verify it: `/check verify IDP login`
- [x] Test it: `/test IDP login`
- [x] Review it (fresh model): `/check review IDP login`
- [x] Document it: `/document IDP login`

### 7. Group to role mapping · done
A learner in a group named exactly like a course gets that one course (spec 0009), and `hol-admins` become admins. The LMS only reads the groups.
**Done when:** a user in a course group gets the student role and that one course, a `hol-admins` user gets admin, and a user in neither is refused. Group changes apply at the next login.
spec [0006](../specs/0006-group-to-role-mapping/index.md), student rule replaced by spec [0009](../specs/0009-course-access-from-groups/index.md) (feature 17) · code in `apps/nile_auth/`, `deploy/scripts/create-site.sh`
- [x] Design it (spec): `/architect group to role mapping`
- [x] Build it: `/develop group to role mapping`
  - [x] Probe the live site, add the `nile_service_user` site setting, and the pure group check with unit tests (AC-4, AC-7)
  - [x] Thin thread: the callback override creates a student and refuses everyone else (AC-1, AC-3)
  - [x] Batches, enrollments, `nile_groups`, admin and both paths, role reconcile (AC-1, AC-2, AC-5, AC-6, AC-11)
  - [x] Safety: early state check, protected accounts, error handling, logs (AC-7, AC-8, AC-9, AC-10, AC-12)
  - [x] Live integration test and README (AC-1 to AC-11)
  - [x] Real Authentik sign in, once feature 6 is up (AC-1, AC-2, AC-3, AC-7)
- [x] Verify it: `/check verify group to role mapping`
- [x] Test it: `/test group to role mapping`
- [x] Review it (fresh model): `/check review group to role mapping`
- [x] Document it: `/document group to role mapping`

### 8. Content sync, one course · done
Push one course from git to Frappe through its API: a YouTube video lesson, a lab guide lesson, and a quiz for each. The thinnest real version of the authoring path.
**Done when:** the sync script creates the course in Frappe from files in git, and running it again updates it without duplicates.
spec [0005](../specs/0005-content-sync/index.md) · code in `tools/src/nile_tools/`, `content/`
- [x] Design it (spec): `/architect content sync`
- [x] Build it: `/develop content sync`
  - [x] Probe the live site, extend the content model, and add the loader and the LMS client (AC-1, AC-3, AC-7)
  - [x] Thin thread, then the full create path with quizzes and outline tables (AC-1, AC-4)
  - [x] Update, removals, progress recompute, and batches (AC-2, AC-5, AC-6, AC-8)
  - [x] `sync --check`, the live integration test, and the README (AC-2, AC-4, AC-5, AC-6, AC-8)
- [x] Verify it: `/check verify content sync`
- [x] Test it: `/test content sync`
- [x] Review it (fresh model): `/check review content sync`
- [x] Document it: `/document content sync`

### 9. Quiz pass rules & certificate · done
A student passes each quiz at 80% or higher, with 3 attempts per quiz, and earns a certificate after every lesson and quiz is complete. A hol-admin publishes the certificate on request, so its link works for LinkedIn.
**Done when:** a student who scores 80% or more on every quiz can request a downloadable certificate, a lower score does not, retakes stop at 3 attempts, and a published certificate link opens for a guest. The content check refuses a pass mark under 80.
spec [0010](../specs/0010-quiz-pass-rules-and-certificate.md) · code in `tools/src/nile_tools/content.py`, `apps/nile_auth/`
- [x] Design it (spec): `/architect quiz pass rules & certificate`
- [x] Build it: `/develop quiz pass rules & certificate`
  - [x] Probe the live site: boundary, attempt limit, certificate, guest link, publish, reset (AC-2 to AC-7)
  - [x] Raise the pass mark floor to 80 in the content check (AC-1)
  - [x] Log learners stranded without a certificate at the login cleanup (AC-9)
  - [x] Integration test and README steps for students and admins (AC-2 to AC-8)
  - [x] Let a Moderator publish or unpublish after the learner is removed: `nile_auth` certificate override, version bump, rebuilt image, test and README (AC-10)
- [x] Verify it: `/check verify quiz pass rules & certificate`
- [x] Test it: `/test quiz pass rules & certificate`
- [x] Review it (fresh model): `/check review quiz pass rules & certificate`
- [ ] Document it: `/document quiz pass rules & certificate`

### 17. Course access from course groups · done
A learner gets only the course they booked. The reservation app puts the learner in an Authentik group named exactly like the course, and Frappe enrolls them in that course only and removes any other course enrollment. Courses stay unpublished, so other courses are hidden and cannot be self enrolled. After the slot a known learner can still sign in and sees only their certificate. Two course groups at once are refused with a clear message.
**Done when:** a learner in the group for course A is enrolled in A only and cannot read or enroll in course B, a learner with no course group reaches only their certificate, two groups at once are refused, and content sync keeps courses unpublished and out of batches. The reservation app and Authentik parts are a contract, built in their own repositories.
spec [0009](../specs/0009-course-access-from-groups/index.md) · code in `apps/nile_auth/`, `tools/src/nile_tools/`, `deploy/`
- [x] Design it (spec): `/architect course access from groups`
- [x] Build it: `/develop course access from groups`
  - Next step after this: `idp test` (finish the IDP login selftest against the course group login; feature 6).
  - [x] Probe the live site, then the pure functions and the thin thread: one learner, one course, no batch (AC-1, AC-4, AC-5, AC-7)
  - [x] Results mode, pruning, admin roles, and the safe login order with the two courses refusal (AC-2, AC-3, AC-6, AC-8, AC-9, AC-10, AC-15)
  - [x] Landing on the course or the profile (AC-11)
  - [x] Content sync keeps courses unpublished and out of batches, and the two student group keys are retired (AC-12, AC-14)
  - [x] Live integration tests, then remove the batch code and the READ COMMITTED setting, then README, cleanup function, and version bump (AC-1 to AC-13)
- [x] Verify it: `/check verify course access from groups`
- [x] Test it: `/test course access from groups`
- [x] Review it (fresh model): `/check review course access from groups`
- [x] Document it: `/document course access from groups`

## Slice 2: look and authoring

### 10. Branding & theme · Beta · done
Apply the Nile brand colors and logos from the Nile design system in `brand/` to the LMS and to the certificate.
**Brand rules to follow:**
- Primary colors: Nile Blue `#0E4EAF`, Deep Nile Blue `#072F68`, Bright Nile Blue `#2070E1`.
- Secondary colors, used intentionally: Solar Amber `#FF6600`, Nile Teal `#35D39A`, Nile Sky `#8BB4EE`, and Dawn Violet `#8758ED`.
- Neutrals: Nile Ink `#001E2D` for text, Nile Slate `#4D626C`, White, and a light background `#F6F8FB`.
- Buttons: the main call to action is Solar Crimson `#EC394C` or Solar Amber `#FF6600`, with white Inter Bold text. The brand gradient (Nile Blue to Solar Amber to Solar Crimson) is for sparing use only.
- Backgrounds: solid Light `#F6F8FB` and `#FFFFFF`, or Dark `#072F68` and `#0E4EAF`.
- Font: Inter only (Semibold for headlines, Regular and Bold for body). Do not substitute or mix other fonts.
- Logo: use the supplied files unchanged. Do not alter, recolor, split, stretch, place inside containers, or put on busy backgrounds, and keep the clear space around it. Questions go to the brand team at brand@nilesecure.com.
- Textures, patterns, and photography are optional extras, not needed for the LMS.
- Design system to reuse: the Nile Hands On Labs design system from the reservations app (github.com/soleng2018/reservations, commit 401b199), which uses the same brand. A copy is in `brand/`: `design-reference.md` (tokens, type scale, radii, shadows, focus rules, component list) and `tokens.css` (the source of truth for values). Its main rules: pill buttons, 16px cards, Inter only, light theme only, Nile Blue for the main action, and text colors adjusted to pass WCAG AA (for example the learner button gradient is `#E91B31` to `#C95100`, and secondary text is `#5D7182`). Its components are React, so for Frappe only the tokens, type, shapes and logos carry over.
- Logo files are in `brand/`: `nile-logo.png` (color), `nile-logo-white.png` (for dark backgrounds), `icon.png` (512 px shield), `apple-icon.png` (180 px), `nile-logo-email.png` (small, for email). They match the files in `/home/nova/lms/site/assets` exactly. Official SVG versions are still owed by the brand owner.
**Approach (decided after research, keep the code small):**
1. Logo, app name, favicon and banner are set through Frappe's Website Settings by a `tools` script. The certificate gets a branded Print Format shipped as a file in `nile_auth`.
2. Colors and Inter for the main app come from one small CSS file that overrides the LMS CSS variables, loaded by a few lines of nginx config in the `frontend` container. This step depends on a live check that the LMS page loads it, and on which variables drive the main button color. Colors and font only.
3. Out of scope: forking LMS or rebuilding its frontend, and the pill button and card shapes. The Authentik login page is branded in Authentik, not here.
**Done when:** the app and the certificate use the brand colors, Inter font, and unaltered logos, set by script so they survive a rebuild, and text on every brand background is readable. The login page is covered only if Authentik branding is done by the same script.
spec [0012](../specs/0012-branding-and-theme/index.md) · code in `apps/nile_auth/`, `deploy/`, `tools/src/nile_tools/`
- [x] Design it (spec): `/architect branding & theme`
- [x] Build it: `/develop branding & theme`
  - [x] Probe the renderer, then install Inter and copy the brand files into the image (AC-1, AC-3, AC-4)
  - [x] The thin certificate: template, setup function, default format, render proof (AC-1, AC-2, AC-6, AC-7, AC-8)
  - [x] App name, logo and favicon by script, and `verify branding` (AC-5, AC-10)
  - [x] Contrast test, then the live probe and the app stylesheet, or record the gap (AC-9, AC-11) (sidebar logo built, task 5a in spec 0012)
  - [x] README and scope row (AC-12)
- [ ] Verify it: `/check verify branding & theme` (skipped at your request, run it when you want an independent check)
- [ ] Test it: `/test branding & theme` (skipped at your request)

### 11. Guide format & full authoring · done
Settle the guide and quiz file format (markdown for text, structured files for quizzes and ordering) and extend the sync to many courses, images, and checks.
**Done when:** a documented format lets an author add a new course by committing files, the sync reports errors in bad files before pushing, and several courses sync cleanly.
spec [0011](../specs/0011-guide-format-and-full-authoring/index.md) · code in `tools/src/nile_tools/`, `content/`, `docs/authoring.md`
- [x] Design it (spec): `/architect guide format & full authoring`
- [x] Build it: `/develop guide format & full authoring`
  - [x] Probe the live site: combined lesson body, public images, explanation field, key uniqueness (AC-2, AC-4, AC-11)
  - [x] Thin thread: lessons as blocks, one course in `content/nile-workshop/`, live `nothing to change` (AC-1, AC-2, AC-8)
  - [x] Quiz files, explanations, the catalog, cross course checks and `content check` (AC-1, AC-3, AC-5, AC-11)
  - [x] Many course sync with isolation, and images with upload and link rewrite (AC-4, AC-7)
  - [x] `content new`, the commit hook, `docs/authoring.md`, README, and a two course live test (AC-6, AC-9, AC-10)
- [x] Verify it: `/check verify guide format & full authoring`
- [x] Test it: `/test guide format & full authoring`
- [x] Review it (fresh model): `/check review guide format & full authoring`
- [x] Document it: `/document guide format & full authoring`

## Slice 3: managers

### 12. Manager progress view · done
Admins in `hol-admins` see each student's progress, quiz scores, and certificate status across all courses.
**Done when:** an admin can list students and see who is not started, in progress, or certified; a student cannot see this view.
spec [0013](../specs/0013-manager-progress-view.md) · code in `apps/nile_auth/nile_auth/nile_auth/report/`
- [x] Design it (spec): `/architect manager progress view`
- [x] Build it: `/develop manager progress view`
  - [x] Thin thread: pure status rules, Learner Progress report with access check, live on the site (AC-1, AC-3, AC-4, AC-10)
  - [x] Complete Learner Progress: flags, exclusions, quiz columns, activity, certificate, filters (AC-2, AC-3, AC-5, AC-6, AC-7, AC-11)
  - [x] Quiz Scores report and links (AC-8, AC-9, AC-11)
  - [x] Integration tests, README admin steps (AC-1 to AC-11)
- [x] Verify it: `/check verify manager progress view`
- [x] Test it: `/test manager progress view`
- [x] Review it (fresh model): `/check review manager progress view`
- [x] Document it: `/document manager progress view`

### 13. Monthly report · in-progress
An on demand report page with a CSV export that summarizes a chosen month: completions, scores, and who is behind.
**Done when:** an admin picks a month and sees the summary, downloads it as CSV, and the numbers match the progress view.
spec [0014](../specs/0014-monthly-report.md) · code in `apps/nile_auth/nile_auth/nile_auth/report/monthly_report/`
- [x] Design it (spec): `/architect monthly report`
- [x] Build it: `/develop monthly report`
  - [x] Thin thread: shared row rule, month filter, Done rule, install and live probes (AC-1 to AC-4, AC-12)
  - [x] Finish rules: Outcome, Done date, certificate rule, date cutoff (AC-3 to AC-5)
  - [x] Month activity and chase columns, filters (AC-6 to AC-8, AC-12)
  - [x] Totals, month dropdown, CSV (AC-2, AC-9, AC-10)
  - [x] Integration tests, README admin steps (AC-1 to AC-12)
- [ ] Verify it: `/check verify monthly report`
- [ ] Test it: `/test monthly report`
- [ ] Review it (fresh model): `/check review monthly report`
- [ ] Document it: `/document monthly report`

## Slice 4: running it safely

### 14. Backup & restore · needs a decision
A scheduled job writes dated backup archives to a local folder on this server (database, uploaded files, and content). A remote host pulls them with scp. A restore command rebuilds the app from an archive.
**Done when:** an archive appears on schedule in a folder the remote host can read over scp, old archives are pruned, and a restore onto a clean setup brings the courses and student progress back.
- [ ] Design it (spec): `/architect backup & restore`

### 16. Health checks & error monitoring · Beta
Container health checks and a simple way to see failures and restarts.
**Done when:** each container reports healthy or unhealthy, and a failing service is visible without reading raw logs.
- [ ] Design it (spec): `/architect health checks & error monitoring`

## Deferred
Out of scope for the current build pass, kept so the plan stays honest.
- **Outbound email** (was #15, Beta): Frappe sends mail through an SMTP server set in the config file, for certificates and notices. Done when a test message sends and a student receives an email when a certificate is issued. Uses `brand/nile-logo-email.png` · needs a decision
- **Emailed monthly report**: send the report to managers on a schedule · needs a decision
- **Accessibility pass**: WCAG AA check on the branded theme
- **Privacy notice and data retention**: notice plus a retention rule for student data · needs a decision
- **Production environment**: a second config, hostname, and secrets · needs a decision
- **Per course managers**: managers who see only their own course · needs a decision
- **Results page after the slot**: a list of a learner's quiz scores per course, beyond the certificate on their profile · needs a decision · from spec 0009
- **Revoke LMS access only**: bind the Authentik LMS application to a group, so one person's LMS access can be removed without deactivating them in every app · needs a decision · from spec 0009

## Legend

**The decision box.** Every feature carries exactly one, the sub-task whose label ends with `(spec)`. Its wording varies (`Design it (spec)` normally, `Decide the stack (spec)` on Stack & architecture), so skills locate it by that `(spec)` suffix, never by an exact label. Every other box is an execution box and `/architect` never ticks one.

**Feature lifecycle**: the scope updates as a feature moves; each row is what it shows and who sets it:

| State | Set by | The feature shows |
|---|---|---|
| `planned` · needs a decision | `/scope` | one box: `Design it (spec): /architect <feature>` |
| `in-progress` (designed) | `/architect` at spec capture | `Design it` ticked; spec linked; `Build it: /develop <feature>` + 2 to 5 milestones; the tier's closing boxes (`Verify it` Alpha+, `Test it` Beta+, `Review it` + `Document it` GA) |
| `in-progress` (building) | `/develop` | milestone sub boxes tick one by one; code pointer filled |
| `in-progress` (verified) | `/check verify` | `Build it` + milestones ticked; `Verify it` ticked |
| `done` | you, when you decide it is; `/sync` reconciles | boxes you ran ticked, skipped ones marked skipped |

- **Next step** = the first unticked box (always a command or a tracked milestone).
- **needs a decision** = run `/architect` first; otherwise straight to `/develop` (or `/audit` for standards & tooling). The tag drops once the spec is captured.
- **Atomic build tasks live in the spec's `## Build plan`, not here**: the scope carries only the milestone rollup.
- **Status** `planned` → `in-progress` → `done`, plus `existing` (pre workflow) and `dropped` (de-scoped, kept for history).
- **Workflow tier tag** beside a heading (e.g. `· Beta`) sets that one feature's rigor below or above the project default (GA); no tag inherits it.
- **Pointer line** (`spec <n> · code in <path>`): the spec link added by `/architect`, the code path by `/develop`.
