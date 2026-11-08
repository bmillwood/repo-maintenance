# repo-maintenance

Idempotent application of various packages of GitHub configuration, run by hand
from a shell where `gh` is logged in as a repo admin.

```sh
uv run repo-maintenance --help
uv run repo-maintenance OPERATION OWNER/REPO...           # dry run
uv run repo-maintenance OPERATION OWNER/REPO... --apply   # make changes, then re-check
```

`--help` describes each operation.

## Development

```sh
uv run ty check
uv run ruff check
uv run ruff format
```

On NixOS the ty and ruff binaries from PyPI can't run, so use them from
nixpkgs instead, e.g. `nix-shell -p ty ruff --run 'ty check'` (ty picks up
`.venv` automatically).
