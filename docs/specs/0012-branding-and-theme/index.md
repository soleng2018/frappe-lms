# 0012. Brand the certificate and the LMS with the Nile look, set by script

**Date**: 2026-11-05
**Status**: Proposed

## Summary

The certificate PDF gets the Nile design from your mockup: Letter size, landscape, a gradient top bar, the Nile logo, the student name, the course title and the public link. It is built as one Print Format (the Frappe template that draws the PDF) that ships as a file inside `nile_auth` and is set as the default by a script that runs on every `make up`. The Inter font is installed in the image, so no PDF ever needs the internet. The same script sets the app name, logo and favicon. The LMS colors and font come last, through one small stylesheet, and only after a live check proves the LMS page accepts it. If it does not, everything else still ships and the gap is written down.

## Requirements

**User stories**:
- As a student, I want my certificate to look like an official Nile credential, with my name, the course and the date, so that I am proud to share it.
- As a student, I want the certificate to show its public link, so that anyone I share it with can open it once an admin has published it.
- As a hol-admin, I want the branding to survive a rebuild and a second `make up` with no manual Desk work, so that nobody has to redo it.
- As the operator, I want one command that proves the branding is in place, so that I can trust a fresh deploy.
- As a student, I want the LMS pages to use the Nile name, logo, font and colors, so that the site feels like the same product as the reservations app.

**Acceptance criteria**:
- **AC-1**: A new certificate renders through a Print Format named `Nile Certificate` as a one page, Letter, landscape PDF (792 by 612 points). The page size, orientation and zero margins are set by a `.print-format` CSS rule in the template (the route Frappe reads into the `wkhtmltopdf` options), with the `pdfkit-` meta tags only as a fallback, and the global Print Settings are never changed. The template resets Frappe's print wrapper (no A4 width, no padding, no letterhead) and its page box is 11 inches wide and at most 8.45 inches high, so `wkhtmltopdf` never adds a blank second page. The design follows the mockup `Nile LMS certificate designs` (the single border version): a top bar that runs from Nile Blue `#0E4EAF` through Bright Nile Blue `#2070E1` to Solar Amber `#FF6600`; a 0.75 point Nile Blue border frame; the unaltered Nile logo at the top left; a pale ring (`#EEF2F8`) at the top right that sits behind and never under any text; the eyebrow `NILE LEARNING` in Nile Blue with wide letter spacing; the title `Certificate of Completion` in Nile Ink; the line `This certificate is proudly presented to`; the student name with a Nile Blue underline; the sentence `for successfully completing the hands on lab requirements for the <course title> certification.` with the course title in bold; and, at the bottom left, a signature line with the labels `Authorized Signature` and `Nile Learning & Enablement`, then `Issued by Nile`, the issue date, `Credential ID: <id>` and the public link. There is no pill label and no second (Advanced) variant. The checks for "the ring never sits under text", "the clear space around the logo" and "nothing overlaps" are made by eye, by comparing a PNG of the PDF page with the mockup in `/check verify`.
- **AC-2**: Every changing value on the PDF comes from the certificate: the student's full name (`doc.member_name`), the course title, the issue date written as `November 5, 2026` (built from the date parts, not from the request language), the credential id (the LMS certificate `name`), and the public link `https://<LMS_HOSTNAME>/courses/<course name>/<certificate name>` (the link form of spec 0010 AC-4). All other text is fixed in the template. Every changing value is HTML escaped (`| e`) before it reaches the page, because the name comes from the identity provider and `wkhtmltopdf` runs the HTML. A certificate that is still private shows the link anyway, and the README says it opens for others only after an admin publishes it.
- **AC-3**: The PDF text is set in Inter (Regular, Semibold, Bold) and the PDF embeds the Inter font, checked with `pdffonts`. The template links no font from the internet. The image build installs pinned static Inter TrueType files (Regular 400, SemiBold 600, Bold 700, from a tagged release, each checked by sha256) and runs `fc-cache`, not the Debian `fonts-inter` package, whose version 4 is likely a variable font that `wkhtmltopdf` cannot take weights from. The CSS uses the family `Inter` with weights 400, 600 and 700. A render with no outside network gives the same result, and it also needs none to show the logo (AC-4).
- **AC-4**: The logo files used are the unchanged files from `brand/`: the copies in the image have the same bytes as `brand/nile-logo.png` and `brand/icon.png`, proved live by `verify branding` (AC-10), since the files exist only in the image. The certificate shows `nile-logo.png` (color), inlined as a base64 data URI by a Jinja method in `nile_auth`, so rendering never fetches a URL. Nothing recolors, crops, stretches or boxes the logo, and the clear space around it is at least half the logo height.
- **AC-5**: A script, `nile_auth.setup.ensure_site_identity`, sets the Website Settings `app_name` to `Nile Learning`, the logo fields (`app_logo` and `banner_image`) to the Nile logo, and `favicon` to the Nile shield icon. It touches only those four fields. It runs from `create-site.sh` on every `make up` after migrate, so a rebuild or a fresh site gets them. A second run changes nothing and says so. The stock LMS certificate template takes its logo from the Website Settings banner image, so this also re-logos any old certificate that still uses the stock template.
- **AC-6**: A script, `nile_auth.setup.ensure_certificate_format`, loads the template from the file shipped in `nile_auth`, creates or updates the Print Format `Nile Certificate` (HTML and CSS from the file, `print_format_for` DocType, `disabled` 0), and sets it as the default print format of LMS Certificate (the Property Setter that LMS reads). It reads each current value, compares it, and writes only a difference, so a second run changes nothing and says so (it never calls `make_property_setter`, which deletes and re inserts every time). It runs from `create-site.sh` on every `make up`. A certificate issued before this change keeps the template it was issued with and is never rewritten (spec 0009 AC-10). Two effects are stated on purpose: every later edit of the template file is reapplied on `make up` and restyles every certificate already issued with `Nile Certificate`, and a change made to `Nile Certificate` by hand in the Desk is overwritten on the next `make up`.
- **AC-7**: The one page layout holds for a student name of 60 characters and a course title of 100 characters: the PDF still has exactly one page, no text is cut off, and nothing overlaps the signature block or the frame. Long text wraps or steps down in size inside its area, by fixed length bands written in the template: for the name, up to 24 characters at 30 pt, 25 to 40 at 24 pt, and 41 or more at 18 pt; for the course title, up to 50 characters at 16 pt and 51 or more at 13 pt. The tests use these bands.
- **AC-8**: Publishing rules are unchanged. A new certificate is private, only a hol-admin publishes it, and a guest gets the PDF only when it is published (spec 0010 AC-5 and AC-10 still pass).
- **AC-9**: The LMS app pages load one stylesheet, `nile-brand.css`, that sets Inter as the font and Nile Blue `#0E4EAF` as the main button and link color, with white button text. This is built only after a live probe shows which method (a Frappe hook, else an nginx rule) makes the LMS page load it and which variables drive the main button. If the probe shows the LMS page cannot take it, this criterion is dropped by a note in `## Follow-up`, and AC-1 to AC-8, AC-10 and AC-11 still ship. The stylesheet changes colors and font only: no shapes, no layout, no fork of LMS. It loads no font or file from another site. The font half is built only if the probe shows the LMS app does not already bundle Inter; then the stylesheet ships a woff2 file in `public/fonts/` with `@font-face`.
- **AC-10**: `make tools CMD="verify branding"` checks the live site and prints one line per item: the Print Format exists, is enabled and is the default, the Website Settings values, the logo and icon URLs answer 200 with the same bytes as `brand/` (the repo is mounted read only in the tools container; the request asks for the file with no image optimization, and a mismatch names that risk), and, when the constant `STYLESHEET_BUILT` in `branding.py` is true, the stylesheet answers 200. It is its own target: plain `verify deploy` is unchanged and does not run it. That Inter is installed in the backend container is checked by a line in the `Makefile` target that runs `docker compose exec backend fc-match -f '%{family}' Inter` before the tools command, because the tools container has no docker access. `verify branding` exits 1 and names every failing item, and it never prints a secret. Running `make up` twice and then `verify branding` passes both times.
- **AC-11**: Every text and background pair used on the certificate and in `nile-brand.css` has contrast of at least 4.5 to 1, proved by a unit test from the hex values (white or `#F6F8FB` with Nile Ink, Nile Slate `#4D626C` and Nile Blue; white on Nile Blue). Amber, Teal, Violet, the gradient and the ring are decoration only and carry no text.
- **AC-12**: `README.md` says what the branding is, that a certificate issued earlier with the stock template keeps its old look apart from the logo, that edits to the template file reach every certificate issued with `Nile Certificate` and that a Desk edit of it is overwritten on the next `make up`, that the printed link works for others only after an admin publishes the certificate, how to run `verify branding`, and where the brand files and the template live. Prerequisites and secrets are unchanged: this spec adds no `.env` key and no system tool. The render test reads the PDF with the Python package `pypdf`, added as a `tools` dev dependency, and not with `poppler` tools.

## Decision

**Chosen option**: Option 1: ship the certificate as a Print Format file in `nile_auth`, apply the branding with idempotent setup functions on every `make up`, and add the app stylesheet last behind a live probe.

The certificate is a hand written HTML and CSS template (a file in `nile_auth`) that the LMS renders to PDF with its own `wkhtmltopdf`. A setup function loads it into the Print Format and makes it the default. The app identity is a second setup function. The Inter font is installed by the image build. The stylesheet for the main app is a small last step that stops at a recorded gap if the LMS does not accept it.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`) · `docker-compose-patterns` (`docker/skills`, `.claude/skills/docker-compose-patterns/`)

## Feature design

**Design source**: the screenshot (the attached PDF `Nile LMS certificate designs`, two pages). Only the single border Foundational page is built. Colors and type come from `brand/design-reference.md` and `brand/tokens.css`.

**Data model sketch**: no new records, fields or migrations. Records written by the scripts:

| Record | Fields set | Notes |
|---|---|---|
| Print Format `Nile Certificate` | `doc_type` LMS Certificate, `custom_format` 1, `print_format_type` Jinja, `pdf_generator` wkhtmltopdf, `html`, `css`, `margin_*` 0, `standard` No | created and updated by `ensure_certificate_format` from the template file |
| Property Setter (LMS Certificate, `default_print_format`) | `value` `Nile Certificate` | read by LMS `get_default_certificate_template` |
| Website Settings (single) | `app_name`, `app_logo`, `banner_image`, `favicon` | only these four, by `ensure_site_identity` |
| LMS Certificate | none changed | `template` is filled at issue from the default (spec 0010) |

**Files shipped in `nile_auth`** (names are the plan, `/develop` may adjust the folder but not the rules):

| File | Purpose |
|---|---|
| `nile_auth/templates/certificate.html` | the Jinja template body, with the page size and orientation set by `pdfkit-` meta tags |
| `nile_auth/templates/certificate.css` | the certificate CSS, written for old WebKit: no grid, no variables, no modern flexbox, tables and absolute positions only |
| `nile_auth/public/images/` | `nile-logo.png` and `icon.png`, copied unchanged from `brand/` by the image build (nothing in this repo edits `brand/`). The folder is git ignored, so a local copy is never committed |
| `nile_auth/public/css/nile-brand.css` | the app stylesheet (AC-9) |
| `nile_auth/branding.py` | pure constants and helpers: the hex tokens, the contrast function, the Print Format name, the app name, the file paths and `STYLESHEET_BUILT`, so the tools tests can import them as they do `mcp_user.py` |
| `nile_auth/certificate.py` (existing file) | gains the Jinja method `logo_data_uri`, registered in `hooks.py` as `jinja = {"methods": ["nile_auth.certificate.logo_data_uri"]}`; it reads the logo with `frappe.get_app_path` and returns a base64 `data:` URI |

**Image build changes** (`deploy/Containerfile`, `.dockerignore`):
- `.dockerignore` allows exactly `brand/nile-logo.png` and `brand/icon.png` besides `apps/nile_auth`, and `COPY` puts them in `nile_auth/public/images/` before the app is copied into the bench. Nothing inside `brand/` is changed.
- The builder links `sites/assets/nile_auth` to `apps/nile_auth/nile_auth/public` (or runs `bench build --app nile_auth`), because the image runs no asset build, so `/assets/nile_auth/...` would otherwise answer 404.
- The pinned Inter TrueType files are downloaded in the build, their sha256 is checked, they are placed in `/usr/share/fonts/truetype/inter/`, and `fc-cache` runs.

**State transitions**: none. The setup functions are rerun safe: each compares the current value to the wanted one and writes only a difference.

**API surface**: no new endpoint. The surfaces touched:

| Surface | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `bench execute nile_auth.setup.ensure_certificate_format` (from `create-site.sh`) | run | the template files | the Print Format and the default, `unchanged` or `updated` | the container, as before | the template file is missing: exit with a message naming the path |
| `bench execute nile_auth.setup.ensure_site_identity` | run | the logo and icon files | the four Website Settings fields | the container | a missing logo file: exit with a message naming the path |
| `/api/method/lms.lms.doctype.lms_certificate.lms_certificate.create_certificate` | POST | `course` | the certificate, with the new template | the student's session | as spec 0010 |
| `/courses/<course name>/<certificate name>` | GET | certificate name | the PDF in the new design | owner always, a guest only if published | as spec 0010 |
| `/assets/nile_auth/images/nile-logo.png`, `.../icon.png`, `.../css/nile-brand.css` | GET | none | the files | public | 404 if the image lacks the files or the assets link, caught by `verify branding` |
| `make tools CMD="verify branding"` | run | `.env` (existing keys) | one line per item, exit 0 or 1 | the service user | a failing item is named, with no secret |

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| Render the certificate | student name | `doc.member_name` (a field of LMS Certificate), escaped with `\| e` |
| Render the certificate | course title | `LMS Course.title` of `doc.course` (`frappe.db.get_value`), escaped with `\| e` |
| Render the certificate | issue date | `doc.issue_date` built as month name, day and year from `getdate(doc.issue_date)` with `strftime("%B")`, the day without a leading zero, and `%Y`, so the request language cannot change it; checked in the render test |
| Render the certificate | credential id | `doc.name`, escaped |
| Render the certificate | public link | `frappe.utils.get_url()` (the site `host_name`, set from `LMS_HOSTNAME` by `create-site.sh`) plus `/courses/` plus `doc.course` plus `/` plus `doc.name`, escaped; it is text only and is never fetched |
| Render the certificate | logo | the Jinja method `logo_data_uri("nile-logo.png")`, which reads the file in `nile_auth/public/images/` and inlines it as a base64 `data:` URI, so no URL is fetched and no network is needed |
| Render the certificate | fixed words (eyebrow, title, signature labels, `Issued by Nile`) | constants in the template file |
| Render the certificate | page size, orientation and margins | a `.print-format` CSS rule in the template (`page-size: Letter; orientation: Landscape; margin: 0`), with the `pdfkit-page-size` and `pdfkit-orientation` meta tags as a fallback; the probe records which one took effect |
| Render the certificate | name and title font sizes | the length bands in AC-7, written in the template |
| Render the certificate | colors | the hex values in `branding.py`, written into the CSS by the same names as `brand/tokens.css` |
| Set the default | the Print Format name | a constant `Nile Certificate` in `branding.py` |
| Set the identity | app name | a constant `Nile Learning` in `branding.py` |
| Set the identity | logo and icon file URLs | `/assets/nile_auth/images/nile-logo.png` and `.../icon.png`, from constants in `branding.py` |
| Verify branding | the wanted values and the byte compare | the same constants, and the bytes of the files in `brand/` read from the read only repo mount in the tools container |
| Verify branding | whether to check the stylesheet | the constant `STYLESHEET_BUILT` in `branding.py`, set true by build task 8 only if AC-9 is built |
| Verify branding | Inter installed | the `fc-match` line in the Makefile target (see AC-10) |
| Contrast test | the pairs and their hex | the constants in `branding.py` |

**Key invariants**:
- The certificate shows only data from the certificate record and fixed text. No score, no email address, and no secret is printed.
- Every brand file in the image is byte for byte the file in `brand/`.
- Both setup functions are rerun safe and touch only the named items. They never delete a Print Format, a certificate or a file.
- No outside network request is needed to render a certificate or to load an LMS page (no Google Fonts, no logo fetch).
- Every value that comes from a record is HTML escaped in the template. No name, however written, can add markup or a request to the PDF page.
- A published or private certificate keeps the same access rules as before (spec 0010).

**Security model**:
- The logo, icon and stylesheet are public files and carry no private data. The template runs inside the Frappe Jinja sandbox and reads only the certificate and the course title. The student's name comes from the identity provider and is untrusted: Frappe's template renderer does not escape, and `wkhtmltopdf` runs the HTML, so an unescaped name could cause a request from the server or a local file read. Every dynamic value is escaped, and a render test uses a name that holds an image tag.
- Only System Manager can edit a Print Format in the Desk, and no student or Moderator right changes. A student still cannot write a certificate.
- The student's name appears on a published certificate (spec 0010). That stays an explicit admin action.
- No regulated data beyond names. No compliance scope applies.

**Configuration required**: none. The hostname comes from the existing `LMS_HOSTNAME`. The name, tokens and file paths are named constants in `branding.py`.

**Edge cases and failure handling**:
- A very long name or title: the template steps the font down by length bands (for example 60 characters or more) and wraps, and the render test proves one page (AC-7).
- The logo file is missing in the image: `ensure_site_identity` exits with a message naming the path before it changes anything, and `verify branding` shows the 404.
- The template file is missing or fails to parse: `ensure_certificate_format` exits before it writes, so the last good format stays the default.
- The logo is inlined from a file in the app, so there is no fetch to fail. If the file is missing the Jinja method raises a clear error naming the path, and the render test and `verify branding` catch it.
- A name written as markup (for example an image tag) prints as plain text and triggers no request.
- Someone disables the Print Format in the Desk: LMS would fall back to another format, so `verify branding` reports a disabled `Nile Certificate`, and the next `make up` sets `disabled` back to 0.
- An old certificate: it renders with its stored template and is not touched.

**Critical test scenarios** (the live ones carry the `integration` marker):
- Happy path: a student with progress 100 requests the certificate and the PDF is one Letter landscape page, holds the name, course title, date, credential id and link, and embeds Inter, verifies **AC-1**, **AC-2**, **AC-3**.
- Failure case: a 60 character name and a 100 character title still give one page with nothing cut off, verifies **AC-7**.
- Failure case: a name that holds an image tag prints as text and causes no request, verifies **AC-2**.
- Idempotence: `make up` run twice leaves the Print Format, the Property Setter and the Website Settings unchanged on the second run, and `verify branding` passes, verifies **AC-5**, **AC-6**, **AC-10**.
- Brand bytes: the logo and icon in the image match `brand/` by sha256, verifies **AC-4**.
- Contrast: a unit test computes every pair from the hex constants, verifies **AC-11**.
- Auth/permission: a guest gets a 403 for a private certificate and the PDF after a hol-admin publishes it, verifies **AC-8**.

## Build plan

The project approach is Tracer Bullet. The first slice is one real thin path from the image to a downloaded, correctly branded PDF. Each later slice thickens one strand.

1. **Probe the renderer** (a throwaway scratch Print Format, not kept): in the live backend, confirm which of the `.print-format` CSS rule and the `pdfkit-` meta tags sets Letter, landscape and zero margins; that Frappe's print wrapper is reset by the template CSS; that a gradient bar, a thick border ring and `border-radius` render; and that a base64 logo shows. Record the findings in `rationale.md` under `## Probe results`, satisfies **AC-1**, **AC-4**
2. **Image build, fonts and brand files**: allow the two brand files in `.dockerignore` and copy them unchanged into `nile_auth/public/images/` (git ignored); link `sites/assets/nile_auth` to the app's `public` folder; install the pinned static Inter TrueType files with a sha256 check and `fc-cache`; rebuild; show `fc-list | grep Inter` in the backend and a 200 for `/assets/nile_auth/images/nile-logo.png`, satisfies **AC-3**, **AC-4**
3. **The thin certificate**: `certificate.html` and `certificate.css` with the full AC-1 and AC-2 content (escaped values, length bands, the `.print-format` rule), `logo_data_uri` in `certificate.py` with its hook, `branding.py`, `ensure_certificate_format` in `setup.py` (read, compare, write only a difference), the call in `create-site.sh`, and a bump of the `nile_auth` version in `pyproject.toml` and `deploy/versions.env` together, satisfies **AC-1**, **AC-2**, **AC-6**
4. **Render proof**: an integration test that issues a certificate on the live site, downloads the PDF and reads it with `pypdf` (add it as a `tools` dev dependency): page count, Letter landscape size, text, embedded Inter fonts, the logo image, the 60 and 100 character case, the image tag name case, and the guest 403 and published cases; and a PNG of the page next to the mockup for the by eye checks, satisfies **AC-1**, **AC-2**, **AC-3**, **AC-7**, **AC-8**
5. **App identity**: `ensure_site_identity`, the call in `create-site.sh`, and a second run proof, satisfies **AC-5**
6. **`verify branding`** in `tools/src/nile_tools/verify.py` and the CLI as its own target, the `fc-match` line in the Makefile target, and unit tests for the pure checks, satisfies **AC-10**
7. **Contrast test** of every pair from the constants in `branding.py`, satisfies **AC-11**
8. **Live probe for the app stylesheet**: find which method loads `nile-brand.css` on the LMS page (the `web_include_css` hook first, an nginx rule second), which variables set the main button color, whether the app already bundles Inter, and which LMS page reads `app_logo`, `banner_image` and `favicon`. Record all of it under `## Probe results`. Then build the stylesheet, set `STYLESHEET_BUILT` and prove Inter and Nile Blue on a live page, or write the gap into `## Follow-up`, satisfies **AC-9**, **AC-10**
9. **README** and the scope row updated in the same turn, satisfies **AC-12**

## Consequences

**Positive**:
- The certificate matches the Nile design, with almost no new moving parts: one template file, two small setup functions, and a font in the image.
- Everything is repeatable by script, so a rebuild or a new site gets the same result with no Desk clicks.
- The Print Format is plain files in git, so a design change is a normal reviewed diff.
- The first slice proves the risky part (what `wkhtmltopdf` can really draw) before the rest is built.

**Negative / tradeoffs**:
- `wkhtmltopdf` is old WebKit, so the design is limited to what it can draw. The gradient bar and the ring are approximations of the mockup and `/check verify` should compare them by eye.
- Old certificates keep their old look. The scripts will not rewrite an issued certificate.
- The certificate prints a link that gives a 403 until an admin publishes the certificate. A printed copy can carry a link that does not open yet.
- A Desk edit of `Nile Certificate` is overwritten on the next `make up`, and every template edit restyles all certificates already issued with it. This is on purpose, so the file in git stays the one source.
- The signature block is a blank line with fixed labels, so a downloaded PDF has no real signature.
- An LMS upgrade can rename its print format or CSS hooks. `verify branding` and the render test are the guard.
- The app stylesheet is the least certain part. The LMS app may not take it, and the spec allows dropping it.

**Neutral**:
- `nile_auth` gets a version bump and a rebuilt image, and `create-site.sh` gains two `bench execute` lines. The image build gains a font download, two brand file copies and an assets link. `tools` gains the dev dependency `pypdf`.
- The Advanced variant, a certificate level key, a generated credential id format and a QR code are not built here.

## Follow-up

- [ ] Advanced certificate variant (double border, amber inner line, level pill): needs a `certificate_level` key in the course file and a custom field, so it is a later spec after feature 11. The mockup page 2 is the design to keep.
- [ ] A signature image or a named signatory, once the brand owner supplies one.
- [ ] Official SVG logos are still owed by the brand owner (scope). Swap the PNG copies when they arrive.
- [ ] Decide whether the verify line should become `nilesecure.com/verify` or a QR code once a Nile verification page exists. Today it shows the LMS public link.
- [ ] Scope row 10 is out of date with this spec in two ways: the setup scripts run inside the container (`nile_auth.setup`), not as a `tools` script, and the stylesheet method is chosen by the probe (hook first, nginx second). Update the row when the spec is confirmed.
- [ ] If the probe in task 8 shows the LMS ignores the stylesheet, record here that app colors need an upstream or fork decision, and mark AC-9 dropped.
- [ ] If an old certificate must change look, an admin can change its `template` field in the Desk. No script does it.

## Rationale

Reasoning and options: see [rationale.md](rationale.md).
