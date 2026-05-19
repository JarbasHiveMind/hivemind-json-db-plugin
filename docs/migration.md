# Schema Migration

`JsonDB` implements `AbstractDB.migrate(from_version)` from
`hivemind-plugin-manager`. The current target is `SCHEMA_VERSION = 2`.

## How it runs

1. On `__post_init__`, the plugin reads a sibling file
   `<name>.schema_version` next to the JSON store
   (`~/.local/share/<subfolder>/<name>.schema_version` by default).
2. If the stored version is lower than `AbstractDB.SCHEMA_VERSION`,
   `migrate(from_version=stored)` runs and then the new version is
   written back to the sentinel file.
3. The migration is idempotent and crash-safe: re-running it on
   already-migrated records is a no-op.

## v1 -> v2

For each stored client record:

- **`intent_blacklist`**, **`skill_blacklist`** at the top level are
  folded into the record's `metadata` dict via `setdefault` — an
  explicit `metadata` value is never clobbered. The top-level keys
  are then dropped.
- **`message_blacklist`** is purged outright (both the top-level key
  and any pre-existing `metadata["message_blacklist"]` from earlier
  migration attempts). The field was removed from the `Client` data
  model in `hivemind-plugin-manager` — it was a 2024-12-20 design
  mistake that contradicted the deny-by-default whitelist model and
  never functioned as a real gate.

After migration the on-disk shape is:

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
written once per migration.

## Compatibility with older `hivemind-plugin-manager`

`_maybe_migrate` reads `getattr(AbstractDB, "SCHEMA_VERSION", 1)`, so
if HPM predates the migration contract the plugin treats the target
as `1` and skips migration. Migration only runs when both sides ship
the new contract.
