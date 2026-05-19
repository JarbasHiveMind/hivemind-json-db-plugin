# Choosing a HiveMind Database Backend

Three first-party HiveMind database plugins ship under the
`hivemind.database` entry-point group. They implement the same
`AbstractDB` contract; the right pick depends on operational
constraints, not feature differences.

| | [`hivemind-json-db-plugin`](https://github.com/JarbasHiveMind/hivemind-json-db-plugin) | [`hivemind-sqlite-database`](https://github.com/JarbasHiveMind/hivemind-sqlite-database) | [`hivemind-redis-database`](https://github.com/JarbasHiveMind/hivemind-redis-database) |
|---|---|---|---|
| Storage | Single JSON file | Single SQLite DB file | Redis (single instance or cluster) |
| External daemon | none | none | Redis server |
| Encryption at rest | optional AES-GCM (`password=...`) | optional via `sqlcipher` extra | TLS in transit; encryption at rest is Redis-side |
| Concurrent writers | single-process | single-process (SQLite WAL: multi-reader, single-writer) | multi-process / multi-host |
| Indexed lookup on `name` / `api_key` | linear scan (O(n)) | indexed (O(log n) via column index) | indexed (Redis sets + optional RediSearch) |
| Whole-file rewrite on commit | yes | no (in-place SQL UPDATE) | no (per-key SET) |
| Hand-editable on disk | yes (any editor / `jq`) | with sqlite CLI | with `redis-cli` |
| VCS-friendly | yes | binary blob | n/a |
| Suitable for ≥ 10k clients | no | yes | yes |
| Suitable for write-churn | no | yes | yes |
| Operationally minimal | yes | yes | no (Redis to run / monitor / back up) |
| Multi-host fleet | no | no | yes |

## When to pick each

### `hivemind-json-db-plugin`

- Single HiveMind node.
- Few dozen to a few thousand clients.
- Static or slowly-changing fleet (provisioned once, edited rarely).
- You want to `cat`, `grep`, `git diff` the database.
- Dev / staging / CI environments.
- Minimal containers — no need for the `sqlite3` C lib or a Redis
  daemon.

This is the **default for `hivemind-core`** and the right starting
point unless you already know you have constraints that rule it out.

### `hivemind-sqlite-database`

- Single host, but write-heavy or large.
- Indexed lookups on `name` / `api_key` matter (e.g. auth path on
  every connection).
- You need encryption at rest with a real key-management story —
  install the `[cipher]` extra and use `sqlcipher`.
- You want WAL-mode multi-reader concurrency (read-only consumers can
  share with a live writer).

### `hivemind-redis-database`

- Multi-process or multi-host HiveMind deployments.
- Shared client DB across a fleet (one Redis serving N HiveMind
  instances).
- You already run Redis for other workloads and want one less data
  store to operate.
- You need pub-sub or cache integration with HiveMind's client state.

## Migration paths

All three implement the same `AbstractDB`, so moving data between them
is a small Python script:

```python
from hivemind_plugin_manager import DatabaseFactory

src = DatabaseFactory.create("hivemind-json-db-plugin")
dst = DatabaseFactory.create("hivemind-sqlite-db-plugin")

for client in src:
    if client.api_key == "revoked":
        continue   # skip tombstones, or copy them if you prefer
    dst.add_item(client)
dst.commit()
```

Then change `database.module` in `server.json` and restart. Keep the
source DB until you're confident the destination holds.

`JsonDB` is the cheapest source to migrate **from** because its
contents are already JSON. See
[Operations → Migration to another backend](operations.md#migration-to-another-backend).

## What's identical across backends

- `Client` dataclass shape — same fields, same property shims, same
  `metadata` semantics.
- The v1→v2 schema migration applies to all three (each implements
  `AbstractDB.migrate()` for its own storage shape; user-visible
  outcome is the same).
- CLI behaviour from `hivemind-core` (`add-client`, `list-clients`,
  `delete-client`, etc.) is backend-independent.
- Policy chain consumption — admission control and the
  `OVOSAgentPolicy` skill/intent blacklists work identically.

If you change backends, no application-level code should need to
change. The differences are all operational.
