# Architecture

## Class hierarchy

```
hivemind_plugin_manager.database.AbstractDB   (abstract)
        │
        └─ hivemind_json_database.JsonDB
                │
                └─ wraps json_database.JsonStorageXDG
                        │  (or EncryptedJsonStorageXDG when password is set)
                        │
                        └─ a dict-like keyed by client_id, persisted as JSON
```

`JsonDB` is intentionally thin: ~110 lines of glue. The interesting
behaviour lives in `json_database.JsonStorage` (the dict-like + atomic
write) and the `AbstractDB` contract.

## On-disk layout

Two files per database under the XDG path
(`$XDG_DATA_HOME/<subfolder>/`):

| File | Purpose |
|---|---|
| `<name>.json` | The store. A JSON object keyed by client_id (stringified on disk). |
| `<name>.schema_version` | Out-of-band sentinel: one ASCII integer ("2") marking the current schema version. |

The encrypted variant replaces `<name>.json` with a binary AES-GCM blob
of the same logical content; `<name>.schema_version` stays plaintext.

### Record shape

Each value in the JSON object is the serialised form of a
`hivemind_plugin_manager.database.Client`. After v2 migration:

```json
{
  "1": {
    "client_id": 1,
    "api_key": "abc-123",
    "name": "kitchen-pi",
    "description": "",
    "is_admin": false,
    "last_seen": 1716120000.0,
    "allowed_types": ["recognizer_loop:utterance"],
    "crypto_key": null,
    "password": null,
    "can_broadcast": true,
    "can_escalate": true,
    "can_propagate": true,
    "metadata": {
      "skill_blacklist": ["weather.skill"],
      "intent_blacklist": ["weather:WeatherIntent"]
    }
  },
  "2": { ... }
}
```

The keys (`"1"`, `"2"`) are `client_id` as strings — JSON has no
integer keys, so this round-trip is unavoidable. Reads coerce back to
int via `Client.__post_init__`.

## Schema-less round-trip

`JsonDB.add_item` stores `copy.deepcopy(client.__dict__)` keyed by
`client.client_id`. The deep copy is intentional — see [Aliasing
semantics](#aliasing-semantics) below.

Because the store is the dict's `__dict__`, it is **schema-less from
the plugin's perspective**: whatever fields are on `Client`,
`JsonStorageXDG` persists. When upstream `hivemind-plugin-manager` adds
a new field, the JSON file picks it up transparently without changes
here.

The flip side: removed fields linger on disk until either re-saved
without them, or explicitly purged by a `migrate()` step. This is the
mechanism the v2 migration uses to retire the legacy blacklist fields.

## Read paths

Both `search_by_value` and `__iter__` go through `cast2client(...)`
from `hivemind_plugin_manager.database` rather than calling
`Client.deserialize` directly. `cast2client` is the more permissive of
the two: it passes through `None`, existing `Client` instances, and
lists, only falling through to `Client.deserialize` for strings and
dicts. Using it on both read paths keeps iteration tolerant of
unexpected record shapes (e.g. a `Client` instance somehow ending up in
storage during in-process mutation).

`search_by_value("client_id", X)` is a direct `dict.get(X)` lookup —
O(1). Every other key falls back to a linear scan over `dict.values()`
— O(n). For workloads that need indexed lookups on arbitrary fields,
this plugin is the wrong choice; see [Comparison](comparison.md).

## Aliasing semantics

`Client` carries several mutable fields: `metadata: Dict`,
`allowed_types: List[str]`, and (until v2) the legacy
`intent_blacklist` / `skill_blacklist` lists. A naïve
`dict(client.__dict__)` would shallow-copy the top-level dict but
share its values, meaning:

```python
client = Client(client_id=1, api_key="k", metadata={"v": "before"})
db.add_item(client)
client.metadata["v"] = "after"   # mutate the same dict the store holds
db.commit()
# Stored record now reflects the post-add mutation — silent corruption.
```

The plugin defends against this by `copy.deepcopy(client.__dict__)` on
insert. A symmetric copy on read would be redundant: `cast2client`
deserialises through `Client(**dict)`, which (because of the dataclass
default factories) creates fresh list/dict instances anyway.

The cost is one deepcopy per `add_item`. For Client records this is
microseconds — not measurable against the JSON write itself.

## Writes and atomicity

`add_item` is memory-only. The first persistence point is `commit()`,
which calls `JsonStorageXDG.store()`. That helper:

1. Writes the new JSON to a temp file in the same directory.
2. `os.replace`s the temp file over the real file.

`os.replace` is atomic on the same filesystem (POSIX `rename(2)`), so
readers either see the old or new version, never a partial write. A
crash between (1) and (2) leaves the old file intact and orphans the
temp file (`combo_lock` cleans up stale temps on next open).

The schema-version sentinel is written separately, without atomic
rename. If the process dies between the migration's `_db.store()` and
`_write_schema_version()`, the disk has v2-shape data but a v1
sentinel — on next open, `migrate()` runs again, finds no legacy keys,
and exits cleanly. Idempotent by construction.

## Sentinel-file rationale

Schema version could have been stored inside the JSON object under a
reserved key (e.g. `__schema_version__`). The sentinel-file approach
was chosen instead because:

- `__iter__`, `__len__`, and `search_by_value` would each need to
  filter out the reserved key, in three places, forever.
- The store's dict shape stays purely `client_id -> Client record`.
- A two-line read function is cheaper than three filter sites.
- For the encrypted variant, the sentinel stays plaintext — operators
  can `cat` it for debugging without needing the password.

The trade-off: one extra small file per database. Negligible.

## Why JSON?

JSON is a deliberate choice, not an accident:

- **Operability.** Operators can read, grep, and diff the database
  with stock Unix tools. Bug reports can include a redacted copy
  pasted into an issue.
- **Recoverability.** A truncated or corrupted line can be fixed by
  hand. A missing field can be added without a schema migration tool.
- **VCS-friendly.** The file diffs cleanly. For static fleets (e.g.
  five HiveMind clients you provisioned once), it's reasonable to
  commit the DB to git.
- **Dependency-light.** No `sqlite3` C lib, no Redis daemon. Useful
  for minimal containers and CI.

The drawbacks (whole-file rewrites, linear search, single-writer) are
all consequences of the same choice. When they bite, switch backends.
