# Getting Started

## Install

```bash
pip install hivemind-json-db-plugin
```

Pulls in:

- `hivemind-plugin-manager >= 0.5.0` — the `AbstractDB` contract and
  `DatabaseFactory` discovery.
- `json_database` — the underlying `JsonStorageXDG` /
  `EncryptedJsonStorageXDG` storage primitives.
- `ovos-utils` — XDG path resolution.

To use the optional AES-GCM encrypted store, also install
`pycryptodomex`:

```bash
pip install pycryptodomex
```

The plugin auto-discovers `pycryptodomex` through `json_database`; you do
not need to import it explicitly.

## Activate via hivemind-core config

The plugin is registered under the `hivemind.database` entry-point group as
`hivemind-json-db-plugin`. Activate it in `~/.config/hivemind-core/server.json`:

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

Or, equivalently, via the `hpm` TUI shipped with `hivemind-plugin-manager`:

```bash
hpm set database hivemind-json-db-plugin
```

After this, every `hivemind-core` subcommand that touches the client
database (`add-client`, `list-clients`, etc.) reads and writes through
this plugin.

## Standalone use (no hivemind-core)

You can also use the plugin programmatically, without `hivemind-core` in
the loop:

```python
from hivemind_plugin_manager import DatabaseFactory
from hivemind_plugin_manager.database import Client

db = DatabaseFactory.create("hivemind-json-db-plugin")

client = Client(client_id=1, api_key="abc-123", name="kitchen-pi")
db.add_item(client)
db.commit()

# Iterate
for c in db:
    print(c.serialize())

# Search
found = db.search_by_value("api_key", "abc-123")
assert len(found) == 1
assert found[0].name == "kitchen-pi"

# Tombstone (revoke)
db.delete_item(client)  # rewrites the entry with api_key="revoked"
db.commit()
```

`db.commit()` is what flushes the in-memory dict to disk. `add_item` /
`delete_item` mutate memory and return immediately; you can batch many
writes between commits.

## What's on disk

After the above, you'll have:

```
~/.local/share/hivemind-core/
├── clients.json          # the database (a JSON object keyed by client_id)
└── clients.schema_version # one-line file: "2"
```

The `.json` file is human-readable — open it, grep it, version-control
it. The `.schema_version` sentinel is written once at first open and
controls whether `migrate()` runs on subsequent opens.

See [Architecture](architecture.md) for what's inside `clients.json`,
[Configuration](configuration.md) for how to relocate it, and
[Operations](operations.md) for backup / hand-editing / recovery.

## Verifying the install

```bash
python -c "
from hivemind_plugin_manager import DatabaseFactory
print(DatabaseFactory.get_class('hivemind-json-db-plugin'))
"
# <class 'hivemind_json_database.JsonDB'>
```

If you get a `KeyError`, your install is broken: the package is missing
or its entry point didn't register. Re-install with `pip install
--force-reinstall hivemind-json-db-plugin`.

## Next

- [Configuration](configuration.md) — encryption, paths, multi-instance
- [Architecture](architecture.md) — on-disk shape, semantics, design notes
- [Operations](operations.md) — backups, recovery, hand-editing
