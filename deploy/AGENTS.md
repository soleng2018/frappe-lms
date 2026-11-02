# Deploy

## Overview

The Docker side of the project: one compose file, the image build, version pins, and the scripts that run inside the containers. Everything is started from the repo root through the `Makefile`, never by calling compose by hand.

## Key files

| File | Owns |
|---|---|
| compose.yaml | Every service, healthcheck, log rotation, and the Traefik labels on `frontend` |
| Containerfile | The layered Frappe image, built from the pinned frappe_docker checkout |
| versions.env | Version and digest pins. Committed on purpose, so git records what is deployed |
| apps.json | Apps baked into the image (LMS by tag, `payments` by branch) |
| fetch-upstream.sh | Checks out frappe_docker at the pinned tag into `deploy/.upstream/` (git ignored) |
| scripts/create-site.sh | One shot site setup. Idempotent, and drops a half made site on rerun |

## Commands

Run from the repo root: `make build`, `make up`, `make down`, `make ps`, `make logs`.

## Conventions

- Settings and secrets come only from the root `.env`. `versions.env` holds pins, never secrets.
- Pin images by digest and upstream sources by tag.
- Every service uses the shared `json-file` log rotation.
- `BUILD_NILE_AUTH_VERSION` in `versions.env` must equal the version in `apps/nile_auth/pyproject.toml`.

## Gotchas

- `make` refuses to run if a config key is exported in your shell, because Compose would let the shell win over `.env`.
- Changing `apps.json` changes the image hash, so the next build picks up new `payments` code.
- Only the Authentik hostname is mapped to the host in `tools`. The LMS is reached through public DNS and Cloudflare.
- Only `frontend` joins the external `traefik` network. No ports are published.

## Related specs

- [0001 Stack and architecture](../docs/specs/0001-stack-and-architecture/index.md)
- [0002 Single config and secrets file](../docs/specs/0002-single-config-and-secrets-file.md)

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
