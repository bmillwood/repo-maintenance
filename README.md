# repo-maintenance

Idempotent application of various packages of GitHub configuration, run by hand
from a shell where `gh` is logged in as a repo admin.

```sh
uv run repo-maintenance --help
uv run repo-maintenance OPERATION OWNER/REPO...           # dry run
uv run repo-maintenance OPERATION OWNER/REPO... --apply   # make changes, then re-check
```

`--help` describes each operation.

Not yet implemented: `renovate-setup`.

## Development

Typecheck with `uv run ty check`. On NixOS the ty wheel from PyPI can't run, so
use `nix-shell -p ty --run 'ty check'` instead (it picks up `.venv`
automatically).
