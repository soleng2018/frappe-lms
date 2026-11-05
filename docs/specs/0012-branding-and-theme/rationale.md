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

_Task 1 is recorded below. Task 8 adds to this section when it runs._

### Task 1: renderer probe (2026-11-05, live backend, Frappe v16.54.0, wkhtmltopdf 0.12.6.1 patched qt)

Method: a scratch Print Format for LMS Certificate rendered with `frappe.get_print(..., as_pdf=True, no_letterhead=1)` on an unsaved certificate, then rolled back. Nothing was committed.

- **Page size comes from the `.print-format` CSS rule only.** This Frappe overrides `_find_options_in_meta` in `frappe/utils/pdf.py` to return nothing, so the `pdfkit-` meta tags are ignored. The rule `.print-format { page-size: Letter; orientation: Landscape; margin-top: 0mm; margin-bottom: 0mm; margin-left: 0mm; margin-right: 0mm; }` gave one page of 792 by 612 points. The same render without the rule gave A4 portrait (595 by 842). The shorthand `margin` is not read (only the four `margin-*` names are), so the template must write all four. The meta tags are dropped from the template, not kept as a fallback, because they do nothing.
- **Rendered fine in wkhtmltopdf:** a `-webkit-linear-gradient` bar (Nile Blue, Bright Nile Blue, Solar Amber), a thick pale ring made from `border` plus `border-radius`, a 0.75 point border frame, absolute positioning, and a base64 PNG logo. The logo showed with `disable-local-file-access` on, since a data URI is not a file read.
- **One page held** with a page box of 11 inches by 8.45 inches and the wrapper padding and width reset by the template CSS.
- **Escaping held.** A name written as `Ada <b>Lovelace</b>` printed as plain text through `| e`.
- **Inter was not installed yet**, so the PDF used DejaVu Sans. Task 2 installs Inter.
