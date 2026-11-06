# 0012. Rationale: brand the certificate and the LMS with the Nile look

Build spec: [index.md](index.md)

## Context

> ⚠️ Premise note: Only half of this feature is certain. The certificate is a template inside LMS's own PDF path, so we control it fully. The main app is a Vue single page app that LMS ships built, and nothing proves it takes an outside stylesheet or exposes one variable for the main button color. That is why the app stylesheet is the last task, sits behind a live probe, and may be dropped without blocking the rest.

The LMS has two looks to brand. The first is the certificate. LMS stores a Print Format on each certificate, renders it with `wkhtmltopdf` (an old WebKit engine with no CSS grid or variables and only old flexbox), and gives the PDF to the student. The default template loads Inter from Google Fonts at render time, sets its logo from the Website Settings banner image, and has no Nile design. The second is the app itself: its name, logo, favicon, font and colors.

The brand rules in the scope are strict: Inter only, logos unchanged, brand colors, readable text on every brand background. The design reference in `brand/` comes from the reservations app, whose components are React, so only tokens, type, shapes and logos carry over. The team is small and runs a dev server, so the solution should be a few files and scripts, not a new app.

The design source is a two page mockup (Foundational and Advanced). The engineer chose to build the Foundational look only, with no pill label, the LMS certificate name as the credential id, and the public link as the verify line. Spec 0010 already fixed how a certificate is issued, kept private, and published. A certificate stores its template when it is issued, so a changed default only affects new ones.

## Options considered

### Option 1: A Print Format file in `nile_auth`, setup functions on every `make up`, and a stylesheet behind a probe

Write the template as an HTML file and a CSS file in `nile_auth`. A setup function loads them into the Print Format and sets the LMS default. A second function sets the app identity. Inter is installed in the image. The app stylesheet is added after a live probe.

**Pros**:
- Plain files in git, reviewed like code, no Desk clicks.
- Idempotent scripts follow the pattern `setup.py` already uses (`ensure_timezone`), so they survive a rebuild.
- Almost no new moving parts and no new app.

**Cons**:
- Limited to what `wkhtmltopdf` can draw.
- The app stylesheet may not load in the LMS page.

### Option 2: Build the certificate with the Print Designer app

Install Frappe's visual Print Designer app and draw the certificate in the Desk.

**Pros**:
- A drag and drop editor, so a non developer can change the layout.

**Cons**:
- A new app to pin, build into the image and keep compatible with `version-16`.
- The design lives in the database, not in git, so it is not reviewed and a rebuild needs an export step.
- It still renders through the same PDF engine, so it does not remove the engine limits.

### Option 3: Render the PDF with our own code

Add a `nile_auth` endpoint that builds the PDF with a library such as WeasyPrint and serves it in place of the LMS route.

**Pros**:
- Modern CSS, full control of fonts and layout.

**Cons**:
- It replaces the LMS download path, which spec 0010 chose to keep, so an LMS upgrade can change it silently.
- A new dependency in the image and new code on a path students use.
- Nothing in the brief needs more than the LMS engine can do.

### Option 4: Edit the stock Certificate Print Format by hand in the Desk

Open the stock format and change it by hand.

**Pros**:
- No code at all.

**Cons**:
- Not repeatable: a new site or a rebuild loses it, and the brief says everything is set up by script.
- A standard format changed by hand is overwritten by an LMS upgrade.

## Rationale

The chosen option fits the forces in Context. The brief wants everything set by script and kept in git, and the team is small, so plain files plus two idempotent functions beat both a new app (Option 2) and a replacement PDF path (Option 3). Option 4 fails the repeatability rule outright. The existing `setup.py` pattern is the right home because the scripts run inside the container with the permissions Frappe needs, and the service user used by `tools` does not need to write the site's Print Format or Website Settings over REST.

The scope text said a `tools` script would set the app name, logo and favicon. The decision moves that into `nile_auth.setup`, run by `create-site.sh` on every `make up`, because that is where timezone and users are already set, it runs with full rights inside the container, and a rebuild reapplies it with no extra command. `tools` still owns the check (`verify branding`). The scope row should be updated to match.

Inter comes from the image build as pinned static TrueType files, not from Google Fonts and not from the Debian package, because the Debian version is likely a variable font that this old renderer cannot take weights from, and because the brand says Inter only and a silent fallback font on a certificate is a brand failure. A render that needs the internet also fails in a locked down network. The engineer chose to self host.

The logo is read from a fixed file in `nile_auth` and inlined as a data URI, not fetched by URL and not taken from the Website Settings banner image as the LMS default does. A URL fetch would go out through public DNS and the proxy and break the no network rule, and an inline file cannot fail that way. A person who changes the banner in the Desk then cannot change the logo on every certificate by accident, and the brand rule says the logo file stays unchanged. The same file is also what `verify branding` compares with `brand/`.

The app stylesheet is last because it is the one uncertain part. The scope proposed an nginx rule. A Frappe `web_include_css` hook needs no nginx change, so the probe tries the hook first and the nginx rule second. The engineer chose to ship the rest and record the gap if the LMS page ignores both. The main button color is Nile Blue because the design reference and its contrast checks set the main action to Nile Blue, and the crimson to amber gradient is for the learner call to action in the reservations app. White on Nile Blue is 7.7 to 1. Solar Amber alone with white text is about 2.9 to 1 and fails AA.

## Probe results

_Task 1 is recorded below. Task 8 adds to this section when it runs. Task 5a adds its File record probe._

### Task 1: renderer probe (2026-11-05, live backend, Frappe v16.54.0, wkhtmltopdf 0.12.6.1 patched qt)

Method: a scratch Print Format for LMS Certificate rendered with `frappe.get_print(..., as_pdf=True, no_letterhead=1)` on an unsaved certificate, then rolled back. Nothing was committed.

- **Page size comes from the `.print-format` CSS rule only.** This Frappe overrides `_find_options_in_meta` in `frappe/utils/pdf.py` to return nothing, so the `pdfkit-` meta tags are ignored. The rule `.print-format { page-size: Letter; orientation: Landscape; margin-top: 0mm; margin-bottom: 0mm; margin-left: 0mm; margin-right: 0mm; }` gave one page of 792 by 612 points. The same render without the rule gave A4 portrait (595 by 842). The shorthand `margin` is not read (only the four `margin-*` names are), so the template must write all four. The meta tags are dropped from the template, not kept as a fallback, because they do nothing.
- **Rendered fine in wkhtmltopdf:** a `-webkit-linear-gradient` bar (Nile Blue, Bright Nile Blue, Solar Amber), a thick pale ring made from `border` plus `border-radius`, a 0.75 point border frame, absolute positioning, and a base64 PNG logo. The logo showed with `disable-local-file-access` on, since a data URI is not a file read.
- **One page held** with a page box of 11 inches by 8.45 inches and the wrapper padding and width reset by the template CSS.
- **Escaping held.** A name written as `Ada <b>Lovelace</b>` printed as plain text through `| e`.
- **Inter was not installed yet**, so the PDF used DejaVu Sans. Task 2 installs Inter.

### Task 5a: File record for the shield (2026-11-05, live backend, Frappe v16.54.0, rolled back)

Method: insert a File row with `file_url` `/assets/nile_auth/images/icon.png` inside a transaction, delete it, check the file on disk, roll back.

- **A plain insert is refused.** `validate_file_path` throws `Cannot access file path /assets/...` (first from `before_insert` through `get_content`, then again in `validate`), because the path is outside the site files folder.
- **Two flags fix it.** `doc.flags.copy_from_existing_file = True` makes `before_insert` skip the blob handling, and `doc.flags.ignore_validate = True` skips `validate`. The insert then succeeds. `ignore_file_validate` is not a Frappe flag and did nothing.
- **Delete is safe.** Deleting that row left `icon.png` on disk (checked before and after).
- **Live result.** After `make up` the guest `get_branding` call returns the shield as `banner_image.file_url`, and a second `make up` prints `Site identity unchanged`.

### Task 8: app stylesheet probe (2026-11-05, signed in look with a throwaway student)

Method: a throwaway LMS Student (`zz-brand-probe@example.com`, deleted afterwards), a session minted inside the backend (password login is off by design and was not touched), and Playwright with Chromium on the host.

- **`web_include_css` cannot reach the LMS app.** The LMS pages are the standalone template `lms/www/_lms.html`, which writes its own `<head>`. The hook route is out.
- **The nginx route works.** The `frontend` container proxies the page to the backend in `location @webserver`. A `sub_filter` that adds a `<link>` before `</head>` is included at server level by a one line `sed` on the upstream template in the image build (`deploy/nginx/nile-brand.conf`). It is added to every HTML page the backend sends, the Desk included, and the stylesheet only names frappe-ui classes.
- **Inter is already bundled.** The built CSS ships `Inter.var-*.woff2` (`font-family: InterVar`) and the signed in page computes `InterVar`. The stylesheet carries no font.
- **Which tokens drive the main button.** The main (solid gray) button is `bg-surface-gray-10` with `hover:bg-surface-gray-9` and `active:bg-surface-gray-8`, text `text-ink-base` (white). It is near black. The blue solid button is `bg-surface-blue-6`. A tooltip style shares `bg-surface-gray-10`, so overriding the token would recolor more than buttons. The rules are limited to `button.bg-surface-gray-10` and `button.bg-surface-blue-6`. The link token is `--ink-blue-link` (stock light blue, under 4.5 to 1 on white), overridden for the light theme only.
- **Live result.** With the stylesheet injected, the main and blue buttons compute to Nile Blue `rgb(14, 78, 175)` with white text (hover `#0A3C87`), the subtle gray button and the tooltip style are unchanged, and links are Nile Blue.
- **Sidebar logo is a gap.** The LMS sidebar draws `banner_image` only when a File record exists for that URL (`get_branding` uses `get_file_info`, a lookup by `file_url` in the File table), and draws it in a 32 by 32 pixel square. Our `/assets/nile_auth/images/nile-logo.png` has no File record, so the sidebar shows the default green icon, and the wide logo would be squashed in that square anyway. The login page and the page title already show the Nile logo and name.
- **Sidebar logo decision (2026-11-05).** Options: (1) shield `icon.png` through a File record, (2) wide logo through a File record with a CSS fit, (3) keep the default green icon. Chose (1). The slot is `w-8 h-8` (32 by 32) in `UserDropdown.vue` and the wide logo is 1922 by 952, so (2) would be a tiny unreadable strip and needs a CSS rule on a frappe-ui class. The shield is 512 by 512, square, and fits as is. Cost: a stock template certificate issued before the Nile format, if any, now shows the shield; new ones inline their own logo. Runner up (3): zero work, but the most visible LMS corner keeps the LMS default brand.
- **Cloudflare note.** The logo URL answered 404 for a moment during the first rebuild, and Cloudflare cached that 404 (max age 4 hours), so a browser showed a broken logo until it was restarted. A fresh browser session fixes it. For the same reason an edit to `nile-brand.css` can take up to 4 hours to reach a browser through the edge cache.
