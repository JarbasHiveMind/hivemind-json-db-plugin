# hivemind-json-db-plugin

JSON-file database plugin for [hivemind-core](https://github.com/JarbasHiveMind/HiveMind-core).
Implements the [`hivemind-plugin-manager`](https://github.com/JarbasHiveMind/hivemind-plugin-manager)
`AbstractDB` contract on top of [`json_database`](https://github.com/TigreGotico/json_database)'s
`JsonStorageXDG`.

## Install

```bash
pip install hivemind-json-db-plugin
```

Optional file encryption (AES via `pycryptodomex`) is available through `json_database`'s
own `EncryptedJsonStorageXDG`; pass `password=...` when instantiating the backend.

## Usage

Activate via `hivemind-core`'s database config:

```json
{
  "database": {
    "module": "hivemind-json-db-plugin",
    "hivemind-json-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core"
    }
  }
}
```

The plugin is registered under the `hivemind.database` entry-point group as
`hivemind-json-db-plugin`, so any `hivemind-plugin-manager`-aware consumer can
discover it via `DatabaseFactory`.

## Schema migration

The plugin overrides `AbstractDB.migrate()` to perform a one-shot
`v1 -> v2` migration on first open:

- Fold legacy top-level `intent_blacklist` / `skill_blacklist` keys into each
  record's `metadata` dict (`setdefault`, so explicit metadata wins).
- Purge `message_blacklist` outright — the field was removed from the `Client`
  data model in `hivemind-plugin-manager`.
- Track schema version in a sibling file (`<name>.schema_version`) next to the
  JSON store, keeping the store's dict shape unchanged.

See [docs/migration.md](docs/migration.md) for details.

## Why a separate repo?

Previously this plugin lived inside `json_database/hpm.py`. Extracting it gives
the plugin its own release cadence (HiveMind-aligned, not OVOS-library-aligned),
removes the `hivemind-plugin-manager` dependency from `json_database` for users
who don't need it, and matches the per-backend repo layout used by the SQLite
and Redis plugins.
