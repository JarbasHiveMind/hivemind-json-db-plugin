import copy
import json
import os
from tempfile import mkstemp
from hivemind_plugin_manager.database import Client, AbstractDB, cast2client
from ovos_utils.log import LOG
from ovos_utils.xdg_utils import xdg_data_home
from typing import Union, Iterable, List, Optional
from json_database import JsonStorageXDG, EncryptedJsonStorageXDG
from json_database.crypto import decrypt_from_json, encrypt_as_json
from dataclasses import dataclass


@dataclass
class JsonDB(AbstractDB):
    """HiveMind Database implementation using JSON files."""
    name: str = "clients"
    subfolder: str = "hivemind-core"
    password: Optional[str] = None

    def __post_init__(self):
        if self.password:
            self._db = EncryptedJsonStorageXDG(encrypt_key=self.password,
                                               name=self.name,
                                               subfolder=self.subfolder,
                                               xdg_folder=xdg_data_home())
        else:
            self._db = JsonStorageXDG(self.name,
                                      subfolder=self.subfolder,
                                      xdg_folder=xdg_data_home())
        LOG.debug(f"json database path: {self._db.path}")
        self._maybe_migrate()

    def _schema_version_path(self) -> str:
        """Sibling file next to the JSON store, kept out-of-band so the
        store's dict shape stays unchanged (keys are still client_ids).
        """
        return os.path.join(os.path.dirname(self._db.path),
                            f"{self.name}.schema_version")

    def _read_schema_version(self) -> int:
        path = self._schema_version_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return int(f.read().strip() or "1")
        except (FileNotFoundError, ValueError, OSError):
            return 1

    def _write_schema_version(self, version: int) -> None:
        path = self._schema_version_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(str(int(version)))
        except OSError as e:
            LOG.warning("JsonDB: failed to write schema_version sentinel: %s", e)

    def _maybe_migrate(self) -> None:
        """Run schema migration if the on-disk version is behind
        ``SCHEMA_VERSION``. Tolerates older HPM that predates the constant.
        """
        target = getattr(AbstractDB, "SCHEMA_VERSION", 1)
        stored = self._read_schema_version()
        if stored < target:
            LOG.info("JsonDB: migrating schema v%d -> v%d", stored, target)
            self.migrate(from_version=stored)
            self._write_schema_version(target)
        self._dirty = set()
        self._baseline = {}

    def migrate(self, from_version: int) -> None:
        """Migrate stored client records to the current ``SCHEMA_VERSION``.

        Idempotent and crash-safe: a partial migration re-run produces
        the same final state. A record with no legacy top-level keys is
        left untouched.

        v1 -> v2: fold each record's top-level ``intent_blacklist`` /
        ``skill_blacklist`` values into the record's ``metadata`` dict
        (``setdefault`` — explicit metadata values are never clobbered),
        then remove the legacy top-level keys. ``message_blacklist``
        is purged outright (the field is not part of the ``Client``
        data model); any residual ``metadata["message_blacklist"]``
        from a prior migration run is also stripped. The store is
        committed once at the end.
        """
        if from_version >= 2:
            return
        legacy_keys = ("intent_blacklist", "skill_blacklist")
        changed_any = False
        for client_id, record in list(self._db.items()):
            if not isinstance(record, dict):
                continue
            metadata = record.get("metadata") if isinstance(
                record.get("metadata"), dict) else {}
            changed = False
            # Strip message_blacklist outright (top-level + metadata).
            if "message_blacklist" in record:
                record.pop("message_blacklist", None)
                changed = True
            if metadata.pop("message_blacklist", None) is not None:
                changed = True
            for lk in legacy_keys:
                if lk in record:
                    val = record.pop(lk)
                    changed = True
                    if val and lk not in metadata:
                        metadata[lk] = list(val) if isinstance(
                            val, (list, tuple)) else val
            if changed:
                record["metadata"] = metadata
                self._db[str(client_id)] = record
                changed_any = True
        if changed_any:
            try:
                self._db.store()
            except Exception as e:
                LOG.error("JsonDB: failed to persist migration: %s", e)

    def sync(self):
        """update db from disk if needed"""
        self._dirty.clear()
        self._baseline.clear()
        self._db.reload()

    def add_item(self, client: Client) -> bool:
        """
        Add a client to the JSON database.

        Args:
            client: The client to be added.

        Returns:
            True if the addition was successful, False otherwise.
        """
        # Deep copy to break aliasing: dict(client.__dict__) is shallow, so
        # mutable fields (metadata dict, intent/skill/message/allowed lists)
        # would otherwise reference caller state and pick up later mutations
        # on the next commit. Snapshot once on insert.
        client_data = copy.deepcopy(client.__dict__)
        cid = str(client.client_id)
        if cid not in self._dirty and cid not in self._baseline:
            # first change to this record since the last commit: keep the
            # pre-change copy as the merge baseline
            self._baseline[cid] = copy.deepcopy(self._db.get(cid))
        self._db[cid] = client_data
        self._dirty.add(cid)
        return True

    def search_by_value(self, key: str, val: Union[str, bool, int, float]) -> List[Client]:
        """
        Search for clients by a specific key-value pair in the JSON database.

        Args:
            key: The key to search by.
            val: The value to search for.

        Returns:
            A list of clients that match the search criteria.
        """
        res = []
        if key == "client_id":
            v = self._db.get(str(val))
            if v:
                res.append(self._hand_out(str(val), v))
        else:
            for client_id, client in self._db.items():
                v = client.get(key)
                if v == val:
                    res.append(self._hand_out(client_id, client))
        return res

    def _hand_out(self, client_id: str, record: dict) -> Client:
        """Build a Client from a stored record and remember the record as
        the merge baseline for that client_id.

        cast2client keeps references to the stored lists and dicts, so a
        caller mutating what it got back changes the in-memory store in
        place. Recording the untouched copy here lets commit() tell the
        fields this instance changed from the fields another instance may
        have advanced.
        """
        if client_id not in self._dirty:
            self._baseline[client_id] = copy.deepcopy(record)
        return cast2client(record)

    def __len__(self) -> int:
        """
        Get the number of clients in the database.

        Returns:
            The number of clients in the database.
        """
        return len(self._db)

    def __iter__(self) -> Iterable['Client']:
        """
        Iterate over all clients in the JSON database.

        Every record goes out through ``_hand_out``, the same path
        ``search_by_value`` uses, so a caller that mutates what it got back
        and then calls ``update_item`` has a pre-change baseline. Without it
        the baseline is taken from the already-mutated record, the merge
        reads the change as untouched, and the on-disk value wins: the
        ``allow-msg`` CLI resolves its client by iterating, so its grant was
        written nowhere.

        Returns:
            An iterator over the clients in the database.
        """
        for client_id, item in list(self._db.items()):
            yield self._hand_out(str(client_id), item)

    @staticmethod
    def _merge_record(mine, baseline, disk_rec):
        """Fold ``mine`` into ``disk_rec`` per field.

        Fields this instance did not touch (equal to ``baseline``) come
        from ``disk_rec`` — another instance may have advanced them. Fields
        it did touch keep this instance's value.
        """
        if baseline is None:
            return copy.deepcopy(mine)
        merged = copy.deepcopy(disk_rec) if isinstance(disk_rec, dict) else {}
        for key, my_val in mine.items():
            if key not in baseline or baseline[key] != my_val:
                merged[key] = copy.deepcopy(my_val)
        return merged

    def commit(self) -> bool:
        """
        Commit changes to the JSON database.

        Each commit carries only the records this instance changed since
        its last commit, merged per field into the on-disk state re-read
        at commit time: a field this instance did not touch keeps the
        value another instance wrote. The whole-record overwrite that let
        one consumer erase another consumer's grant is gone.

        A missing on-disk record counts as no baseline: the full record
        this instance holds is written back, never a partial one.

        A commit with no pending changes writes nothing.

        The whole write holds the store lock, so no other consumer can
        commit between the re-read and the write.
        """
        try:
            baselines = {cid: self._baseline.get(cid) for cid in self._dirty}
            mine = {cid: dict(self._db[cid])
                    for cid in self._dirty if cid in self._db}
            self._dirty.clear()
            self._baseline.clear()
            if not mine:
                # nothing changed here: write nothing, a read-only close
                # must not erase a concurrent instance's newer records
                return True
            merged = {cid: self._merge_record(rec, baselines.get(cid), None)
                      for cid, rec in mine.items()}
            with self._db.lock:
                disk = self._read_disk_locked()
                if disk is not None:
                    for cid, rec in merged.items():
                        if cid in disk:
                            merged[cid] = self._merge_record(
                                rec, baselines.get(cid), disk.get(cid))
                        else:
                            # a record no longer present in the store file
                            # has no baseline: write the full record this
                            # instance holds, never a partial merge
                            baseline_here = baselines.get(cid)
                            if baseline_here is not None:
                                full = copy.deepcopy(rec)
                                full.update({
                                    k: v for k, v in
                                    (baselines[cid] or {}).items()
                                    if k not in full
                                })
                                merged[cid] = full
                    disk.update(merged)
                    self._db.clear()
                    self._db.update(disk)
                payload = self._serialize(
                    disk if disk is not None else dict(self._db))
                # write under the same lock hold, atomic; the store lock is
                # not reentrant, store() cannot be called while it is held
                self._atomic_write_locked(payload)
            return True
        except Exception as e:
            LOG.error(f"Failed to save {self._db.path} - {e}")
            return False

    def _read_disk_locked(self) -> Optional[dict]:
        """Read the store file while the store lock is held.

        Returns the plain records. An encrypted store is decrypted here,
        so the merge sees the same shape the in-memory dict has. Returns
        ``None`` when the file exists but cannot be read or decrypted;
        the caller then keeps the in-memory dict, which is the behaviour
        before this change on an unreadable file.
        """
        if not os.path.isfile(self._db.path):
            return {}
        try:
            with open(self._db.path, "r", encoding="utf-8") as f:
                raw = json.load(f) or {}
        except (ValueError, OSError) as e:
            LOG.warning("JsonDB: cannot re-read %s before commit: %s",
                        self._db.path, e)
            return None
        if not self.password or not raw:
            return raw
        try:
            return json.loads(decrypt_from_json(self.password, raw))
        except Exception as e:
            LOG.warning("JsonDB: cannot decrypt %s before commit: %s",
                        self._db.path, e)
            return None

    def _serialize(self, records: dict) -> str:
        """Serialize the records the same way the storage class does.

        An encrypted store stays encrypted: the payload is the AES-GCM
        envelope, never the plain records. ``EncryptedJsonStorage.store``
        cannot do this step here, because the store lock is held and is
        not reentrant.
        """
        if self.password:
            envelope = json.loads(encrypt_as_json(self.password, records))
            return json.dumps(envelope, indent=4, ensure_ascii=False)
        return json.dumps(records, indent=4, ensure_ascii=False)

    def _atomic_write_locked(self, payload: str) -> None:
        """Write the store file atomically while the store lock is held.

        The mode of an existing store file is preserved: ``mkstemp``
        creates the temporary file at 0600, and without this step
        ``os.replace`` would carry that mode onto a store an operator
        set group-readable on purpose.
        """
        path = os.path.realpath(self._db.path)
        try:
            old_mode = os.stat(path).st_mode & 0o7777
        except OSError:
            old_mode = None
        fd, tmp_path = mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            if old_mode is not None:
                os.chmod(tmp_path, old_mode)
            os.replace(tmp_path, path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
