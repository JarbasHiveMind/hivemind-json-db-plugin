# Operations

Backup, restore, hand-editing, and recovery for `JsonDB` on disk.

## Locating the files

By default:

```
~/.local/share/hivemind-core/clients.json
~/.local/share/hivemind-core/clients.schema_version
```

Substitute `$XDG_DATA_HOME` if set, and `<subfolder>` / `<name>` if
configured otherwise. See [Configuration](configuration.md).

## Backups

The unencrypted store is a single text file. Any backup tool you
already use works:

```bash
# Snapshot before maintenance
cp ~/.local/share/hivemind-core/clients.json \
   ~/.local/share/hivemind-core/clients.json.bak.$(date +%F)

# Roll into your normal rsync / restic / borg pipeline
restic backup ~/.local/share/hivemind-core/
```

**Always include both files** — `clients.json` and
`clients.schema_version`. Restoring just the JSON file with a stale
sentinel triggers a migration on the next open, which is harmless but
noisy in logs. Restoring just the sentinel with the wrong JSON gives
you incoherent state.

For the encrypted variant, the same applies — the binary file backs up
like any other.

### Live-process backups

`JsonDB`'s `commit()` is atomic (temp-file + `os.replace`), so a backup
taken with a live HiveMind process is safe **as long as** you copy the
file in a single read (`cp`, not `cat > file`). Tools like `rsync`
that handle their own atomic moves are fine.

If you want a stronger guarantee (no half-written state for any
observer, ever), stop the HiveMind process for the duration of the
copy. The cost is whatever your client-disconnect tolerance is.

## Restore

```bash
# Stop the HiveMind process first
systemctl --user stop hivemind-core   # or however you run it

# Restore both files
cp /backup/clients.json ~/.local/share/hivemind-core/clients.json
cp /backup/clients.schema_version ~/.local/share/hivemind-core/clients.schema_version

systemctl --user start hivemind-core
```

If you only have the JSON file (older backup, sentinel lost), restore
it and **delete** any stale sentinel:

```bash
rm -f ~/.local/share/hivemind-core/clients.schema_version
```

On next open, `_maybe_migrate()` will see version `1` (the fallback for
a missing sentinel), run the v1→v2 migration (no-op if the data is
already in v2 shape), and write a fresh sentinel.

## Hand-editing

The unencrypted file is JSON. You can edit it directly with any editor
or `jq`:

```bash
# Stop the process — JsonDB is single-writer
systemctl --user stop hivemind-core

# Edit
jq '.["3"].name = "renamed-pi"' clients.json > clients.json.new
mv clients.json.new clients.json

# Or just open in $EDITOR
$EDITOR ~/.local/share/hivemind-core/clients.json

systemctl --user start hivemind-core
```

The plugin reads the file on open and reconstructs `Client` instances
via `cast2client(...)`. Any field the dataclass knows about
round-trips; unknown fields are silently dropped on the next write
(the plugin re-serialises from `client.__dict__`, not from the original
JSON).

**Required invariants:**

- The file must be a valid JSON **object** (`{...}`), not an array.
- Each value must be an object with at minimum `client_id` (int) and
  `api_key` (str).
- The key must be the stringified `client_id`. A mismatch
  (key `"3"`, value `client_id: 7`) is read with the value's
  `client_id` winning — the key is just a dict slot.

If you violate these, the next `commit()` may either ignore your edit
silently or refuse to load the file at startup. Keep a backup before
editing.

## Searching from the shell

For ad-hoc queries without booting HiveMind:

```bash
# List all clients by name
jq -r 'to_entries[] | "\(.value.client_id)\t\(.value.name)\t\(.value.api_key)"' clients.json

# Find clients with a specific allowed_type
jq 'to_entries[] | select(.value.allowed_types | contains(["recognizer_loop:utterance"])) | .value' clients.json

# Show all admins
jq 'to_entries[] | select(.value.is_admin == true) | .value.name' clients.json
```

## Recovery from corruption

If the JSON file is truncated or invalid:

1. **First, try the backup** — that's what backups are for.
2. **If no backup**, try to repair the trailing braces. JSON
   corruption usually looks like a half-written final record.
   ```bash
   python -m json.tool clients.json   # shows the first parse error
   ```
   Open in an editor, close the dangling structure, save.
3. **If a record is unsalvageable**, delete it. A missing client is
   recoverable (issue a new `api_key`); a corrupted DB is not.

`json_database`'s `JsonStorage` is intentionally strict — it does
**not** try to recover partial files automatically. If `commit()` ever
encounters a write error, the existing file stays untouched (atomic
rename only happens on success). Corruption from this layer's writes
is therefore very rare; the usual cause is filesystem-level events
(power loss without WAL, disk full).

## Auditing schema migrations

Check the current on-disk version:

```bash
cat ~/.local/share/hivemind-core/clients.schema_version
# 2
```

To force a migration re-run (e.g. after restoring an old backup):

```bash
rm ~/.local/share/hivemind-core/clients.schema_version
# Next process start runs _maybe_migrate() from v1
```

The migration is idempotent, so this is always safe.

To verify the v2 shape on disk:

```bash
# Should be empty (no top-level legacy keys after v2)
jq 'to_entries[] | .value | keys[]
     | select(. == "intent_blacklist" or . == "skill_blacklist"
              or . == "message_blacklist")' clients.json
```

If that produces output, either migration didn't run (delete the
sentinel and restart) or a hand-edit reintroduced a legacy key (remove
it).

## Multi-environment management

For dev/staging/prod separation on a single host, override
`subfolder` or `$XDG_DATA_HOME`:

```bash
# Dev
XDG_DATA_HOME=~/hivemind-dev hivemind-core listen
# -> ~/hivemind-dev/hivemind-core/clients.json

# Staging
XDG_DATA_HOME=~/hivemind-staging hivemind-core listen
# -> ~/hivemind-staging/hivemind-core/clients.json
```

For multi-host fleets, the JSON file is **not** the right vehicle.
Pick Redis.

## Migration to another backend

`JsonDB` is the easiest backend to migrate **from**, because the data
is right there as JSON:

```python
import json
from hivemind_plugin_manager.database import Client
from hivemind_plugin_manager import DatabaseFactory

with open("clients.json") as f:
    records = json.load(f)

new_db = DatabaseFactory.create("hivemind-sqlite-db-plugin")
for raw in records.values():
    new_db.add_item(Client(**raw))
new_db.commit()
```

Then flip the `database.module` in `server.json` from
`hivemind-json-db-plugin` to `hivemind-sqlite-db-plugin`, restart, and
keep the JSON file as a backup until you're confident the new backend
holds.
