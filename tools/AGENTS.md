# Tools

## Overview

The `nile_tools` Python package: config handling, the `init` and `config check` commands, and later the Authentik and content sync scripts. It runs in a container as the `tools` service, with the repo mounted at its host path.

## Key files

| File | Owns |
|---|---|
| src/nile_tools/config.py | The one key list (`KEYS`), the strict `.env` parser, validators, generators, sample rendering, secret masking |
| src/nile_tools/checks.py | The checks behind `config check` |
| src/nile_tools/cli.py | The command line: `init`, `config`, `whoami` |
| tests/ | Unit tests, plus `*_integration.py` files that need the running stack |

## Commands

```bash
make tools CMD="config check"    # run any tools command in the container
make tools CMD="config sample"   # print the .env.sample generated from the key list
```

## Conventions

- `KEYS` in `config.py` is the single source for `.env.sample`. Add a key there, then regenerate the sample.
- Integration tests carry the `integration` marker and are skipped by default (`-m 'not integration'`).
- Unit tests never touch the network or a real `.env`.

## Gotchas

- The container runs under your own uid, so a test that passes on the host can still fail there. HOME and caches point at `/tmp`.
- The runtime image installs with `--no-dev`, so it has no linters or pytest.
- `config check` runs `git` inside the container for the secret scan, which is why the image installs git and sets `safe.directory`.

## Related specs

- [0002 Single config and secrets file](../docs/specs/0002-single-config-and-secrets-file.md)
- [0003 Coding standards and tooling](../docs/specs/0003-coding-standards-and-tooling.md)

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
