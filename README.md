# hivemind-json-db-plugin

JSON-file database backend for [hivemind-core](https://github.com/JarbasHiveMind/HiveMind-core).

Implements the [`hivemind-plugin-manager`](https://github.com/JarbasHiveMind/hivemind-plugin-manager)
`AbstractDB` contract on top of [`json_database`](https://github.com/TigreGotico/json_database)'s
`JsonStorageXDG`. Client records (API keys, crypto keys, access-control lists) are stored as a
single JSON file on disk.

This backend is well-suited for development, small deployments, and single-host hubs where
simplicity and zero infrastructure dependencies matter more than query speed.

## Where it fits

```
hivemind-core
  └── hivemind-plugin-manager  (DatabaseFactory loads plugins by entry-point)
        └── hivemind-json-db-plugin  ← this repo
              └── json_database (JsonStorageXDG / EncryptedJsonStorageXDG)
```

The plugin registers under the `hivemind.database` entry-point group as
`hivemind-json-db-plugin`. `hivemind-core` loads it automatically when `server.json`
sets `database.module` to this name; you never instantiate `JsonDB` directly in normal
usage.

## Install

```bash
pip install hivemind-json-db-plugin
```

## Quickstart

Add or update the `"database"` block in `~/.config/hivemind-core/server.json`:

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

Then start (or restart) hivemind-core:

```bash
hivemind-core listen
```

The database file is created automatically at
`$XDG_DATA_HOME/hivemind-core/clients.json` (typically `~/.local/share/hivemind-core/clients.json`).

### Optional encryption

Enable AES encryption via `json_database`'s `EncryptedJsonStorageXDG`:

```json
{
  "database": {
    "module": "hivemind-json-db-plugin",
    "hivemind-json-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core",
      "password": "your-strong-passphrase"
    }
  }
}
```

> **Warning**: There is no password recovery. If you lose the passphrase the database
> is permanently unrecoverable. Back up the passphrase securely.

An encrypted database cannot be opened without the passphrase; a plain database cannot
be opened as encrypted. There is no automatic migration between the two modes.

## Configuration reference

| Key | Default | Description |
|---|---|---|
| `name` | `"clients"` | Base filename (without extension) for the JSON store. |
| `subfolder` | `"hivemind-core"` | XDG subfolder under `$XDG_DATA_HOME`. |
| `password` | `null` | When set, enables AES encryption via `EncryptedJsonStorageXDG`. |

## Schema migration

On first open after an upgrade, `JsonDB` runs an automatic one-shot schema migration
that folds legacy `intent_blacklist` / `skill_blacklist` top-level keys into each
record's `metadata` dict and purges the removed `message_blacklist` field.

The migration is idempotent and crash-safe. See [docs/migration.md](docs/migration.md)
for full details.

To migrate an existing installation to this backend, use hivemind-core's built-in
command:

```bash
hivemind-core migrate-db
```

## Docs

- [docs/architecture.md](docs/architecture.md) — internals, sentinel-file rationale, encrypted-store sentinel
- [docs/migration.md](docs/migration.md) — schema migration details, v1→v2, forcing a re-migration
- [docs/configuration.md](docs/configuration.md) — full configuration reference
- [docs/operations.md](docs/operations.md) — file locations, backup, restore, authoring a plugin
