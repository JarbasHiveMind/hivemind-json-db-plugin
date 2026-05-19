# Configuration

`JsonDB` accepts three optional constructor parameters. Defaults match
the layout `hivemind-core` expects out-of-the-box.

| Parameter | Default | Effect |
|---|---|---|
| `name` | `"clients"` | Basename of the JSON file (no extension). Written as `<name>.json`. The schema-version sentinel is `<name>.schema_version`. |
| `subfolder` | `"hivemind-core"` | XDG subfolder under `$XDG_DATA_HOME`. The full path is `$XDG_DATA_HOME/<subfolder>/<name>.json`. |
| `password` | `None` | If set (non-empty), switches storage to AES-GCM encrypted (`EncryptedJsonStorageXDG`). See [Encryption](#encryption) below. |

All three are passed via the `hivemind-json-db-plugin` config block in
`~/.config/hivemind-core/server.json`:

```json
{
  "database": {
    "module": "hivemind-json-db-plugin",
    "hivemind-json-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core",
      "password": null
    }
  }
}
```

## Paths

`JsonDB` uses `ovos_utils.xdg_utils.xdg_data_home()` for the data root,
which follows the XDG Base Directory Specification:

- If `$XDG_DATA_HOME` is set, use it.
- Otherwise, default to `~/.local/share`.

With the default `name` / `subfolder`, the full path resolves to:

```
$XDG_DATA_HOME/hivemind-core/clients.json
~/.local/share/hivemind-core/clients.json     # most Linux setups
```

The directory is created on first write — no upfront `mkdir` needed.

### Relocating the database

To put the DB somewhere else, change `subfolder` (relative to
`$XDG_DATA_HOME`) or override `$XDG_DATA_HOME` itself:

```bash
# Per-process
XDG_DATA_HOME=/srv/hivemind hivemind-core listen
# Resolves to /srv/hivemind/hivemind-core/clients.json
```

For arbitrary absolute paths (outside `$XDG_DATA_HOME`), there is no
config knob — use a symlink in `$XDG_DATA_HOME/hivemind-core/` pointing
to the real file. The plugin reads and writes through that symlink
transparently.

### Multiple HiveMind instances on the same host

If you run two `hivemind-core` instances on one box, give them distinct
`name` or `subfolder` values so they don't share a file. The plugin
does not coordinate access between processes — see
[Concurrency](#concurrency-and-multi-instance).

## Encryption

Passing a non-empty `password` switches the backend from
`JsonStorageXDG` to
[`EncryptedJsonStorageXDG`](https://github.com/TigreGotico/json_database/blob/dev/docs/ENCRYPTION.md):

```json
{
  "database": {
    "module": "hivemind-json-db-plugin",
    "hivemind-json-db-plugin": {
      "name": "clients",
      "password": "a-16-byte-key!"
    }
  }
}
```

**Properties:**

- AES-GCM over a zlib-compressed JSON blob.
- The file on disk is **not** valid JSON — it's a binary container.
  You cannot `cat` / `jq` it.
- The same `name` / `subfolder` resolution applies; the file just isn't
  human-readable.

**Cryptographic caveats (inherited from `json_database`):**

- **Key length:** the underlying primitive truncates keys longer than 16
  bytes silently. Use **exactly 16 bytes**. Pad or hash to that length
  yourself; do not pass a 32-byte key expecting AES-256.
- **No key rotation:** there is no built-in re-key flow. To change the
  password you must read the DB with the old key, write a new DB with
  the new key.
- **No HSM, no KMS:** the password is whatever string you put in
  `server.json`. Treat that file as a secret. Set its mode to `0600`.
- **At-rest only:** the data is plain in process memory while
  `JsonDB` is loaded.

For threat models that exceed those constraints, use a different
backend (e.g. an OS-level encrypted volume hosting the JSON file, or
SQLite with `sqlcipher`).

## Concurrency and multi-instance

`JsonDB` is **single-writer**. The underlying `JsonStorage` uses
`combo_lock` for in-process write safety, but two separate
`hivemind-core` processes pointed at the same `clients.json` file will
race on writes — the last commit wins, and an interrupted write can
truncate the file mid-update.

If you need concurrent multi-process access, use
[`hivemind-redis-database`](https://github.com/JarbasHiveMind/hivemind-redis-database)
or [`hivemind-sqlite-database`](https://github.com/JarbasHiveMind/hivemind-sqlite-database)
(SQLite's WAL mode tolerates multi-reader / single-writer safely).

## Capacity guidance

- **Up to a few thousand clients:** comfortable. Whole-file rewrites
  on `commit()` stay under tens of milliseconds.
- **10k+ clients or write-heavy:** the whole-file rewrite cost shows.
  Move to SQLite.
- **Sharded across hosts:** out of scope; use Redis.

## Schema version

The plugin tracks its on-disk schema version in a sibling file
(`<name>.schema_version`) next to the JSON store. This is created
automatically on first open after install. See [Migration](migration.md)
for what version transitions do and how to recover from a stale
sentinel.
