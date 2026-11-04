# 0007 rationale. Prove the LMS runs behind Traefik and close the gaps

**Date**: 2026-11-03
**Status**: In Progress

## Context

Mode: ENHANCEMENT of what spec 0001 built, on the existing stack (Python tools, Docker Compose, Traefik v3.5.0, Frappe `version-16` at 16.54.0). The scope row says done when the LMS opens over HTTPS, survives a restart, and logs rotate. A live probe on 2026-11-03 found:

- HTTPS works at the configured hostname: `/api/method/ping` returns 200, assets load, and the socket.io handshake returns 200. Traffic arrives through Cloudflare, which talks to Traefik over HTTPS using a Cloudflare Origin certificate (see `deploy/compose.yaml`, `tools` service comment).
- `http://<host>/` returns 200 with the site. Cloudflare forwards plain HTTP requests to the origin over HTTPS, so Traefik never sees an HTTP request. A Traefik redirect would not help real visitors. The redirect has to happen at Cloudflare.
- `/api/v2/mcp` is public. Frappe already protects it: a Guest gets 401, and a signed in user needs the System User type. `enable_mcp` in System Settings defaults on. Credentials are the normal `Authorization: token key:secret` header. Spec 0001 left the decision on it to this feature.
- Restart policy `unless-stopped` and `json-file` rotation (10m, 5 files) are set on the services. Nothing proves they hold after a rebuild or that the stack heals after a kill.
- The `tools` container has no Docker socket, so it cannot restart containers.

## Rationale

Reasoning and options are inline below, kept short because this is an enhancement of a working deploy.

**Options considered**

*Option 1: Document only.* Write the proof steps in the README and fix nothing. Pros: no code. Cons: the checks rot, the MCP question stays open, and the gaps stay.

*Option 2: Tools command plus host script.* Chosen. Pros: matches the repo rules (Python in `tools`, pure functions, unit tests), reusable after every rebuild, one MCP key per consumer. Cons: two entry points, because Docker control cannot run inside `tools`.

*Option 3: Move the redirect and checks into Traefik config.* A CF-Visitor header rule on the secure router to redirect, plus Traefik middleware for headers. Pros: redirect in git. Cons: leans on a Cloudflare header, adds labels to the one router that must stay simple, and you chose the Cloudflare toggle.

**Why Option 2**: The probe showed the deploy itself is sound, so the work is proof and the three gaps, not new infrastructure (simple beats clever). Frappe already authenticates the MCP endpoint, so keeping it public behind a separate key costs one user, while blocking it would remove what you asked for. A Traefik HTTP redirect was dropped because Cloudflare terminates public HTTP. You asked for read and write for the agent; that works, and the cost is drift against git, recorded above. The runner up for the restart proof was a policy only check, which is cheap but proves the least.
