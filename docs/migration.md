# Schema Migration

`JsonDB` implements `AbstractDB.migrate(from_version)` from
`hivemind-plugin-manager`. The current target is `SCHEMA_VERSION = 2`.

## How it runs

1. On `__post_init__`, the plugin reads a sibling file
   `<name>.schema_version` next to the JSON store
   (`$XDG_DATA_HOME/<subfolder>/<name>.schema_version` by default).
2. If the stored version is lower than `AbstractDB.SCHEMA_VERSION`,
   `migrate(from_version=stored)` runs, then the new version is written
   back to the sentinel file.
3. The migration is **idempotent and crash-safe**: re-running it on
   already-migrated records is a no-op.

Migration is **eager** — it happens on the first `JsonDB(...)`
construction after install, before any read or write. The cost on a
small DB (≤ few thousand clients) is sub-second; large DBs see one
linear scan + one whole-file rewrite.

## v1 → v2

For each stored client record:

- **`intent_blacklist`**, **`skill_blacklist`** at the top level are
  folded into the record's `metadata` dict via `setdefault` — an
  explicit `metadata` value is never clobbered. The top-level keys
  are then dropped.
- **`message_blacklist`** is **purged outright**, with no
  carry-forward (both the top-level key and any pre-existing
  `metadata["message_blacklist"]` from an earlier migration attempt
  are stripped). The field was a 2024-12-20 design mistake that
  contradicted the deny-by-default whitelist model and was removed
  from the `Client` data model in HPM. See the HPM PR #27 thread for
  the full audit.

After migration, the on-disk shape is:

```json
{
  "1": {
    "client_id": 1,
    "api_key": "...",
    "name": "...",
    "allowed_types": ["recognizer_loop:utterance"],
    "metadata": {
      "skill_blacklist": ["weather.skill"],
      "intent_blacklist": ["weather:WeatherIntent"]
    }
  }
}
```

## Schema-version sentinel

Storing the version out-of-band (in a sibling file) rather than as a
reserved key inside the JSON store keeps the store's dict shape pure
`client_id -> record` — no special-case filtering in `__iter__`,
`__len__`, or `search_by_value`. The cost is one extra small file
written once per migration. See
[Architecture → Sentinel-file rationale](architecture.md#sentinel-file-rationale).

The sentinel file contains a single ASCII integer (currently `2`):

```bash
$ cat ~/.local/share/hivemind-core/clients.schema_version
2
```

A missing or unparseable sentinel is treated as version `1` — i.e.
"unmigrated, run the migration".

## Compatibility with older `hivemind-plugin-manager`

`_maybe_migrate()` reads
`getattr(AbstractDB, "SCHEMA_VERSION", 1)`. If you happen to run this
plugin against an HPM that predates the `SCHEMA_VERSION` constant, the
plugin treats the target as `1` and skips migration — the data stays
in v1 shape, which the older HPM also understands. Migration only runs
when both sides ship the new contract.

This makes the plugin safe to ship alongside a not-yet-released HPM:
upgrade either side independently, no crash.

## Forcing a re-migration

If you restored an old backup and want the migration to run against
it:

```bash
rm ~/.local/share/hivemind-core/clients.schema_version
# next process start runs _maybe_migrate() from v1
```

Idempotency guarantees this is always safe — if the JSON is already in
v2 shape, the migration is a no-op and the sentinel just gets rewritten.

## Future versions

If a future `SCHEMA_VERSION = 3` (or beyond) ships in HPM, this
plugin's `migrate(from_version)` will need a `v2 -> v3` branch.
Migrations always go forward from the stored version — there is no
support for downgrades.

Implementation pattern for adding a v3:

```python
def migrate(self, from_version: int) -> None:
    if from_version < 2:
        self._migrate_v1_to_v2()
    if from_version < 3:
        self._migrate_v2_to_v3()
    # ...etc, sequential and idempotent
```

Each step takes the disk from version N to N+1; running them in
sequence advances from any older version. Idempotency for each step
is enforced by the "look for legacy shape, do nothing if absent"
pattern the v1→v2 code already uses.

## Verifying the migration ran

```bash
$ cat ~/.local/share/hivemind-core/clients.schema_version
2

# Should be empty (no legacy top-level keys after v2):
$ jq 'to_entries[] | .value | keys[] |
       select(. == "intent_blacklist" or . == "skill_blacklist"
              or . == "message_blacklist")' \
    ~/.local/share/hivemind-core/clients.json
```

If that `jq` produces output, either:

- The migration did not run (the sentinel is missing or stuck at `1` —
  see [Troubleshooting → Migration ran on every start](troubleshooting.md#migration-ran-on-every-start)).
- Or a hand-edit reintroduced a legacy key. Remove it.
