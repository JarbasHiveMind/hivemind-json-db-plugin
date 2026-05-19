# Contributing

## Dev setup

```bash
git clone https://github.com/JarbasHiveMind/hivemind-json-db-plugin
cd hivemind-json-db-plugin
pip install -e ".[dev]"
```

The `[dev]` extras pull in `pytest`. The runtime extras
(`hivemind-plugin-manager`, `json_database`, `ovos-utils`) come from
the base install.

## Running tests

```bash
pytest tests/ -q
```

Expected output: `17 passed`. The suite covers metadata round-trip,
deep-copy aliasing, the v1→v2 migration (folds, idempotency,
`setdefault` non-clobber, residual `message_blacklist` purge), and
end-to-end re-open with the schema_version sentinel.

The tests use `tmp_path` and `monkeypatch` to redirect
`xdg_data_home()` per test — no XDG pollution, safe to run in
parallel.

## Coding conventions

- Single source file: `hivemind_json_database/__init__.py`. If
  something grows large enough to warrant splitting, split — but keep
  the public surface (`JsonDB`) importable from the package root.
- The module is intentionally **thin**. Storage primitives live in
  `json_database`; the `AbstractDB` contract lives in
  `hivemind-plugin-manager`. This package is glue. Resist the urge to
  reimplement storage features here.
- Comments explain **why**, not what. Code is allowed to be obvious.
- Tests are mandatory for any behaviour change. Add a failing test
  first, then make it pass.

## Versioning

Versions are bumped automatically by the gh-automations CI workflows
from conventional-commit prefixes. **Do not edit `version.py` by
hand.**

Commit prefix → bump:

| Prefix | Bump |
|---|---|
| `feat:` / `feat(scope):` | minor |
| `fix:` / `fix(scope):` | patch |
| `refactor:`, `chore:`, `docs:`, `test:`, `ci:` | alpha |
| `BREAKING CHANGE:` in body | major |

The release workflow picks up the bump on PR merge to `dev`, then
gates a stable promotion via a `dev -> master` PR.

## Branch model

- `dev` is the integration branch. Open PRs against `dev`.
- `master` is stable. Promoted from `dev` via release PR.
- Feature branches: `feat/<short-name>`, `fix/<short-name>`,
  `refactor/<short-name>`, etc.

## Pull request checklist

- [ ] `pytest tests/ -q` passes locally.
- [ ] Conventional-commit prefix on the PR title and the squash-commit.
- [ ] Docs updated if the change touches public API, config, or
  on-disk shape.
- [ ] CHANGELOG entry (gh-automations will append on release, but if
  the change is significant, write the human summary yourself).

## Release process

Driven by gh-automations:

1. Merge PR to `dev`. The `Release Alpha and Propose Stable` workflow
   fires:
   - Bumps `version.py` from commit prefixes.
   - Appends to CHANGELOG.
   - Tags an alpha and publishes to PyPI as a prerelease.
   - Opens a `dev -> master` "propose stable" PR.
2. Merge the propose-stable PR to cut a stable release. The
   `Release Stable` workflow publishes the non-alpha version.

No manual `setup.py sdist` / `twine upload` — the workflow handles it.

## CI

- **Build Tests** (`.github/workflows/build-tests.yml`) — `pytest` on
  Python 3.10–3.14. Pulls in `hivemind-plugin-manager@dev` until the
  next HPM release; once HPM is on PyPI, drop the
  `pre_install_pip` override.
- **Coverage** (`.github/workflows/coverage.yml`) — coverage report on
  Python 3.11, posts a PR comment.
- **Lint** (`.github/workflows/lint.yml`) — `ruff` / `flake8`.
- **License Check** (`.github/workflows/license_check.yml`) — verifies
  dependency licenses against the allowlist.
- **pip-audit** (`.github/workflows/pip_audit.yml`) — scans deps for
  known CVEs.
- **Repo Health** (`.github/workflows/repo-health.yml`) — periodic
  hygiene checks.

If a workflow fails on a PR, fix the root cause; don't `--no-verify`
your way around it.

## Issue triage

Bug reports should include:

- `pip show hivemind-json-db-plugin hivemind-plugin-manager json_database`
- The `<name>.schema_version` content.
- A redacted snippet of `clients.json` (replace `api_key` /
  `crypto_key` with `<redacted>`).
- The full traceback.

See [Troubleshooting](troubleshooting.md) for common issues that don't
need to be filed.
