# Troubleshooting

Common failure modes and how to diagnose them.

## `KeyError: 'hivemind-json-db-plugin'`

The plugin isn't installed, or its entry point didn't register.

```bash
pip show hivemind-json-db-plugin
# Should print Name, Version, Location, etc.
```

If installed, check the entry-point group is visible to Python:

```bash
python -c "
from importlib.metadata import entry_points
for ep in entry_points(group='hivemind.database'):
    print(ep.name, '->', ep.value)
"
```

You should see `hivemind-json-db-plugin -> hivemind_json_database:JsonDB`.
If not, the install is corrupt:

```bash
pip install --force-reinstall hivemind-json-db-plugin
```

This sometimes happens after editable installs (`pip install -e`) get
out of sync with the metadata cache. The `--force-reinstall` rebuilds
the entry-point manifest.

## `ImportError: cannot import name 'JsonDB'`

You probably have the old `json_database.hpm:JsonDB` import in your
code. The plugin has been extracted into its own package — update:

```python
# Before
from json_database.hpm import JsonDB

# After
from hivemind_json_database import JsonDB
```

The `hivemind.database` entry-point name is unchanged
(`hivemind-json-db-plugin`), so config files in `server.json` don't
need an update — only direct Python imports do.

## `ImportError: pycryptodomex` (when using `password=...`)

The encrypted variant needs `pycryptodomex`:

```bash
pip install pycryptodomex
```

It's not a hard dependency of `hivemind-json-db-plugin` because most
deployments don't use the encrypted form.

## "Password must be exactly 16 bytes" (or silent truncation)

`json_database`'s `EncryptedJsonStorage` accepts longer keys but
**silently truncates** to 16 bytes. If you set a 32-byte password
expecting AES-256, you're actually using the first 16 bytes — AES-128.

Use exactly 16 bytes:

```python
password = "abcdef0123456789"   # 16 ASCII chars
```

Or derive from a longer secret:

```python
import hashlib
password = hashlib.sha256(secret.encode()).hexdigest()[:16]
```

See [Configuration → Encryption](configuration.md#encryption) for the
full caveat list.

## `JsonDecodeError` on load

The JSON file is corrupt. Causes:

- An out-of-band edit broke the syntax.
- A power loss between `os.write` and `os.replace` truncated the temp
  file (rare — atomic rename should prevent the actual file being
  affected, but a sufficiently old fs can fail).
- Disk full during a commit (the temp file is incomplete, but the real
  file should still be intact — check it first).

Fix per [Operations → Recovery from corruption](operations.md#recovery-from-corruption).

## "Migration ran on every start"

The `<name>.schema_version` sentinel file isn't being written. Common
causes:

- The directory is read-only (e.g. `clients.json` lives in a baked-in
  container layer). `_write_schema_version` logs a warning and
  swallows the `OSError`. Move the file to a writable location.
- A different user owns the file and the current process can't write
  the sentinel. Fix permissions.

The migration itself is idempotent — re-running it is harmless, but
the log noise indicates a real config problem.

## "Client metadata I set isn't there after restart"

You called `add_item` but not `commit`. `add_item` is memory-only;
`commit()` is what writes to disk. If your process exits before
commit, the change is lost.

`hivemind-core` calls `commit()` after every CLI write
(`add-client`, `delete-client`, etc.). If you're calling `add_item`
directly from Python (e.g. in a script), add the `commit()`.

## "Stored metadata mutated after I committed"

You hit an aliasing bug — but `JsonDB` defends against this by
deep-copying on insert. If you're seeing the symptom anyway, check:

- Are you holding a reference to the dict returned from
  `db._db[client_id]` and mutating it? That's an internal view, and
  the plugin doesn't track mutations on the returned reference. Don't
  do that — call `add_item` with a new `Client` to update.
- Are you running an old `hivemind-json-db-plugin` predating the
  deep-copy fix? `pip show` and upgrade if so.

## "Two processes are stomping on each other's writes"

`JsonDB` is single-writer. Two `hivemind-core` instances against the
same `clients.json` race on `commit()`, and the loser's changes are
lost.

Either:

- Run a single `hivemind-core`.
- Point each instance at a separate file (`name=` or `subfolder=`).
- Use a different backend
  ([`hivemind-redis-database`](https://github.com/JarbasHiveMind/hivemind-redis-database)
  for multi-process, or `hivemind-sqlite-database` for multi-process
  on a single host with SQLite's WAL).

## "After upgrading HPM, every read crashes with `TypeError: unexpected keyword argument 'message_blacklist'`"

This was a hazard in an earlier HPM rebuild that has since been fixed
— make sure you're on HPM ≥ the policy-plugins release (see HPM
PR #27). The current contract is: `Client(message_blacklist=...)` is
accepted and discarded with a `DeprecationWarning`, not a `TypeError`.

If you're stuck on an interim build, upgrade HPM:

```bash
pip install -U hivemind-plugin-manager
```

## "Where do I report bugs?"

[github.com/JarbasHiveMind/hivemind-json-db-plugin/issues](https://github.com/JarbasHiveMind/hivemind-json-db-plugin/issues).

Useful info for a bug report:

- Output of `pip show hivemind-json-db-plugin hivemind-plugin-manager json_database`.
- The `<name>.schema_version` content (`cat`).
- A **redacted** snippet of `clients.json` showing the affected record(s).
  Replace `api_key` and `crypto_key` with `<redacted>` — these are
  credentials.
- The full traceback if any.
