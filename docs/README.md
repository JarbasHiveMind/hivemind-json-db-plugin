# hivemind-json-db-plugin — Documentation

JSON-file database backend for [`hivemind-core`](https://github.com/JarbasHiveMind/HiveMind-core).
Implements the [`hivemind-plugin-manager`](https://github.com/JarbasHiveMind/hivemind-plugin-manager)
`AbstractDB` contract on top of
[`json_database`](https://github.com/TigreGotico/json_database)'s `JsonStorageXDG`.

This is the simplest of the three first-party HiveMind database backends —
single-file, plain JSON on disk, no daemon, optional AES-GCM encryption.
Recommended for small single-node deployments, dev environments, and CI.

---

## Where to look

| You want to... | Read |
|---|---|
| Install and run for the first time | [Getting Started](getting-started.md) |
| Configure paths, encryption, server.json | [Configuration](configuration.md) |
| Understand the on-disk layout and design trade-offs | [Architecture](architecture.md) |
| Look up `JsonDB` methods | [API Reference](api-reference.md) |
| Read schema migration semantics | [Migration](migration.md) |
| Back up, restore, edit by hand, recover | [Operations](operations.md) |
| Diagnose an error or oddity | [Troubleshooting](troubleshooting.md) |
| Decide between JsonDB / SQLite / Redis | [Comparison](comparison.md) |
| Contribute code or open a PR | [Contributing](contributing.md) |

---

## When to pick this plugin

**Pick `JsonDB` when:**
- You have a single HiveMind node and a few dozen to a few thousand clients.
- You want the database to be a text file you can `cat`, `grep`, edit, and
  commit to git.
- Your client list changes infrequently — every write rewrites the whole file.
- You want zero external dependencies (no SQLite library, no Redis server).

**Pick something else when:**
- You have tens of thousands of clients or write churn — use
  [`hivemind-sqlite-database`](https://github.com/JarbasHiveMind/hivemind-sqlite-database)
  for an indexed, in-place-updated store.
- You need to share a client DB between multiple HiveMind processes or nodes —
  use [`hivemind-redis-database`](https://github.com/JarbasHiveMind/hivemind-redis-database).
- You need encryption with key rotation, audit logs, or HSM-backed keys — the
  optional `password=...` here is AES-GCM symmetric, which suits *at-rest*
  protection but not key-management workflows.

See [Comparison](comparison.md) for the full matrix.

---

## A 60-second tour

```python
from hivemind_plugin_manager import DatabaseFactory

db = DatabaseFactory.create("hivemind-json-db-plugin")
# -> <JsonDB ... path=~/.local/share/hivemind-core/clients.json>

db.add_item(Client(client_id=1, api_key="abc", name="kitchen-pi",
                   allowed_types=["recognizer_loop:utterance"]))
db.commit()

for client in db:
    print(client.client_id, client.name)
```

The plugin is registered under the `hivemind.database` entry-point group as
`hivemind-json-db-plugin`. Any `hivemind-plugin-manager`-aware consumer
discovers it automatically.
