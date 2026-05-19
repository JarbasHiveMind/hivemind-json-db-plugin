# API Reference

## `hivemind_json_database.JsonDB`

```python
@dataclass
class JsonDB(AbstractDB):
    name: str = "clients"
    subfolder: str = "hivemind-core"
    password: Optional[str] = None
```

Backend implementation of `hivemind_plugin_manager.database.AbstractDB`
on top of `json_database.JsonStorageXDG`.

### Constructor parameters

| Param | Type | Default | Effect |
|---|---|---|---|
| `name` | `str` | `"clients"` | Basename of the JSON file (no extension). |
| `subfolder` | `str` | `"hivemind-core"` | XDG subfolder under `$XDG_DATA_HOME`. |
| `password` | `Optional[str]` | `None` | If set (non-empty), use `EncryptedJsonStorageXDG` (AES-GCM). |

Construction is side-effecting: the file is opened (or created) at
`$XDG_DATA_HOME/<subfolder>/<name>.json`, and `_maybe_migrate()` runs
once to bring the on-disk shape up to `AbstractDB.SCHEMA_VERSION`.

See [Configuration](configuration.md) for full semantics.

### `add_item(client: Client) -> bool`

Insert or overwrite a record keyed by `client.client_id`. Always
returns `True`.

`client.__dict__` is deep-copied before storage to break aliasing —
post-`add_item` mutations on the caller's `Client` do not leak into the
stored record. See [Architecture → Aliasing semantics](architecture.md#aliasing-semantics).

Memory-only. Call `commit()` to persist.

### `delete_item(client: Client) -> bool`

Inherited from `AbstractDB`. Replaces the record at `client.client_id`
with a tombstone (`Client(client_id=X, api_key="revoked")`) and calls
`update_item`. The slot stays allocated — `client_id`s are never
reused. Returns whatever `update_item` returned.

### `update_item(client: Client) -> bool`

Inherited from `AbstractDB`; calls `add_item`.

### `replace_item(old_client: Client, new_client: Client) -> bool`

Inherited from `AbstractDB`; calls `delete_item(old)` then
`add_item(new)`. Note that this leaves a revoked tombstone at
`old.client_id` and a fresh record at `new.client_id`. If you want to
edit a record in place, just call `add_item` with the updated `Client`
— it overwrites by `client_id`.

### `search_by_value(key: str, val) -> List[Client]`

Return every stored client whose attribute named `key` equals `val`.

- `key="client_id"` uses `dict.get(val)` — **O(1)**.
- Every other key falls back to a linear scan — **O(n)**.

The matching is exact equality (`==`). No substring, no regex, no
case-folding.

### `__iter__() -> Iterable[Client]`

Yield every stored record as a `Client`. Order matches insertion order
(Python dicts preserve insertion order; the JSON store does too).
Includes tombstoned records (`api_key="revoked"`) — filter at the call
site if you need only live ones.

### `__len__() -> int`

Return the number of stored records, including tombstones. The
`<name>.schema_version` sentinel does **not** count — it's a sibling
file, not a record.

### `sync() -> None`

Re-read the file from disk into memory. Use this if you suspect the
file was modified out-of-band (e.g. by another process or a manual
edit) and want to pick up the changes without restarting.

`sync()` does not write — any uncommitted in-memory changes since the
last `commit()` are **discarded**. Commit first if you have pending
writes.

### `commit() -> bool`

Persist the in-memory dict to disk. Returns `True` on success, `False`
on any exception (which is also logged via `ovos_utils.log.LOG`).

Atomic on POSIX: writes to a temp file in the same directory, then
`os.replace`s it over the target. Readers see either the old or new
state, never a partial write.

### `migrate(from_version: int) -> None`

Schema migration hook from `AbstractDB`. Called automatically by
`__post_init__` via `_maybe_migrate()` if the on-disk schema version is
behind `AbstractDB.SCHEMA_VERSION`.

`v1 -> v2`: fold legacy top-level `intent_blacklist` / `skill_blacklist`
into each record's `metadata` dict (`setdefault`); purge
`message_blacklist` outright (top-level **and** any residual
`metadata["message_blacklist"]` from a prior migration run); commit
once at the end. Idempotent — re-runs are no-ops.

You should not normally need to call this directly. See
[Migration](migration.md) for the full contract.

### Private / internal

The following are implementation details, not part of the stable API:

- `_db` — the underlying `JsonStorage(XDG)` instance.
- `_schema_version_path()` — full path to the sentinel sibling file.
- `_read_schema_version() -> int` — reads the sentinel, returns 1 on
  missing / unparseable.
- `_write_schema_version(version: int)` — writes the sentinel.
- `_maybe_migrate()` — invokes `migrate()` if needed and bumps the
  sentinel.

These can change between releases.

## `hivemind_json_database.__version__`

Standard `__version__` string sourced from
`hivemind_json_database/version.py`. Bumped automatically by the
gh-automations release workflow from conventional-commit prefixes; do
not edit by hand.

## Entry point

```toml
[project.entry-points."hivemind.database"]
"hivemind-json-db-plugin" = "hivemind_json_database:JsonDB"
```

Discoverable via `hivemind_plugin_manager.DatabaseFactory`:

```python
from hivemind_plugin_manager import DatabaseFactory
cls = DatabaseFactory.get_class("hivemind-json-db-plugin")
db = DatabaseFactory.create("hivemind-json-db-plugin",
                            name="clients",
                            subfolder="hivemind-core")
```
