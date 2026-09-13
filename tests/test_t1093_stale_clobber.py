"""Two consumers of one JSON store silently destroy each other's writes.

JsonDB.commit() wrote the whole in-memory store over the file, so any
instance running since before another one committed could drop that
other one's records on disk. The live case: the CLI grants a message
type and commits; the server, holding a copy loaded before the grant,
later writes a whole client record (last-seen tracking) and the grant is
gone after a restart. See knowledge/wiki/audits/hivemind/allowmsg-1029-repro.md.

Each instance must re-read the store at commit time and write back only
its own changed records, the way the sqlite backend already behaves
(INSERT OR REPLACE of a fresh row).
"""
import os

from hivemind_plugin_manager.database import Client

from hivemind_json_database import JsonDB
import hivemind_json_database as hpm

VOICE_SAT_DEFAULT = "recognizer_loop:utterance"
GRANT = "ovos.utterance.handle"


def make_db(tmp_path, monkeypatch) -> JsonDB:
    monkeypatch.setattr(hpm, "xdg_data_home", lambda: str(tmp_path))
    return JsonDB()


def make_client(**kwargs) -> Client:
    return Client(**kwargs)


def test_grant_survives_stale_whole_record_write(tmp_path, monkeypatch):
    """Instance A loads before instance B's allow-msg grant; A then writes
    a whole record (last-seen flow) and commits. B's grant must survive."""
    # B provisions the client and commits
    db = make_db(tmp_path, monkeypatch)
    db.add_item(make_client(client_id=1, api_key="k", name="sat",
                            allowed_types=[VOICE_SAT_DEFAULT]))
    assert db.commit()

    # A opens BEFORE the grant, so its copy holds no grant
    db_a = make_db(tmp_path, monkeypatch)
    stale = db_a.search_by_value("api_key", "k")[0]
    assert stale.allowed_types == [VOICE_SAT_DEFAULT]

    # B grants a message type and commits (the allow-msg flow)
    db_b = make_db(tmp_path, monkeypatch)
    granted = db_b.search_by_value("api_key", "k")[0]
    granted.allowed_types.append(GRANT)
    db_b.update_item(granted)
    assert db_b.commit()

    # A updates last seen on its stale record and commits
    stale.last_seen = 1234.5
    db_a.update_item(stale)
    assert db_a.commit()

    fresh = make_db(tmp_path, monkeypatch)
    found = fresh.search_by_value("api_key", "k")
    assert len(found) == 1
    assert found[0].allowed_types == [VOICE_SAT_DEFAULT, GRANT]
    assert found[0].last_seen == 1234.5


def test_read_only_instance_commit_does_not_clobber(tmp_path, monkeypatch):
    """ClientDatabase opens and closes a commit on every use, even when the
    consumer only read clients. A read-only close must not erase another
    instance's newer record."""
    db = make_db(tmp_path, monkeypatch)
    db.add_item(make_client(client_id=1, api_key="k", name="sat",
                            allowed_types=[VOICE_SAT_DEFAULT]))
    assert db.commit()

    db_a = make_db(tmp_path, monkeypatch)  # opened before the update
    assert len(list(db_a)) == 1

    db_b = make_db(tmp_path, monkeypatch)
    client = db_b.search_by_value("api_key", "k")[0]
    client.allowed_types.append(GRANT)
    db_b.update_item(client)
    assert db_b.commit()

    # A closes without any change; its commit must write nothing
    assert db_a.commit()

    fresh = make_db(tmp_path, monkeypatch)
    found = fresh.search_by_value("api_key", "k")
    assert found[0].allowed_types == [VOICE_SAT_DEFAULT, GRANT]


def test_revoked_tombstone_survives_other_instances_commit(tmp_path, monkeypatch):
    """delete_item keeps the record with api_key="revoked" as a tombstone.
    A stale instance committing an unrelated write must not resurrect the
    revoked record."""
    db = make_db(tmp_path, monkeypatch)
    db.add_item(make_client(client_id=1, api_key="k1", name="a",
                            allowed_types=[VOICE_SAT_DEFAULT]))
    db.add_item(make_client(client_id=2, api_key="k2", name="b"))
    assert db.commit()

    db_a = make_db(tmp_path, monkeypatch)  # holds both records alive
    assert len(list(db_a)) == 2

    # B revokes client 2
    db_b = make_db(tmp_path, monkeypatch)
    gone = db_b.get_client_by_id(2)
    db_b.delete_item(gone)
    assert db_b.commit()

    # A writes client 1 only
    c1 = db_a.search_by_value("api_key", "k1")[0]
    c1.last_seen = 7.0
    db_a.update_item(c1)
    assert db_a.commit()

    fresh = make_db(tmp_path, monkeypatch)
    assert fresh.get_client_by_id(1).last_seen == 7.0
    reloaded = fresh.get_client_by_id(2)
    assert reloaded is None or reloaded.api_key == "revoked", \
        "an unrelated commit resurrected a revoked client"


def test_other_instance_records_not_lost_when_two_records_change(tmp_path, monkeypatch):
    """Both instances change different records; each commit carries only its
    own record, and both changes end up on disk."""
    db = make_db(tmp_path, monkeypatch)
    db.add_item(make_client(client_id=1, api_key="k1", name="a",
                            allowed_types=[VOICE_SAT_DEFAULT]))
    db.add_item(make_client(client_id=2, api_key="k2", name="b"))
    assert db.commit()

    db_a = make_db(tmp_path, monkeypatch)
    db_b = make_db(tmp_path, monkeypatch)

    a1 = db_a.search_by_value("api_key", "k1")[0]
    a1.last_seen = 11.0
    db_a.update_item(a1)

    b2 = db_b.search_by_value("api_key", "k2")[0]
    b2.allowed_types.append(GRANT)
    db_b.update_item(b2)
    assert db_b.commit()
    assert db_a.commit()

    fresh = make_db(tmp_path, monkeypatch)
    assert fresh.get_client_by_id(1).last_seen == 11.0
    assert GRANT in fresh.get_client_by_id(2).allowed_types


def test_commit_hold_lock_across_merge_and_write(tmp_path, monkeypatch):
    """A commit landing between the merge and the write inside commit() is
    erased by the write, because the write happens outside the lock. The
    lock must be held across re-read, merge AND write."""
    import threading
    import time as _time

    db = make_db(tmp_path, monkeypatch)
    db.add_item(make_client(client_id=1, api_key="k", name="sat",
                            allowed_types=[]))
    assert db.commit()

    # this instance will commit a last_seen change
    db_a = make_db(tmp_path, monkeypatch)
    stale = db_a.search_by_value("api_key", "k")[0]
    stale.last_seen = 42.0
    db_a.update_item(stale)

    inner_commit_ran = []
    in_write = threading.Event()

    # widen the window on the call the commit really makes: the outer
    # write announces that it started and then sleeps before it replaces
    # the file. The competing commit waits for that announcement, so it
    # always runs while the outer commit is inside its write. It can
    # only get the lock there if the write happens outside the lock,
    # which is the regression this test guards.
    real_write = db_a._atomic_write_locked

    def slow_write(payload):
        in_write.set()
        _time.sleep(0.5)
        real_write(payload)

    monkeypatch.setattr(db_a, "_atomic_write_locked", slow_write)

    def _inner_commit():
        assert in_write.wait(timeout=10), "the outer write never started"
        db_b = make_db(tmp_path, monkeypatch)
        granted = db_b.search_by_value("api_key", "k")[0]
        granted.allowed_types.append(GRANT)
        db_b.update_item(granted)
        assert db_b.commit()
        inner_commit_ran.append(True)

    t = threading.Thread(target=_inner_commit)
    t.start()
    assert db_a.commit()
    t.join(timeout=10)
    monkeypatch.undo()
    assert inner_commit_ran

    fresh = make_db(tmp_path, monkeypatch)
    found = fresh.search_by_value("api_key", "k")
    assert len(found) == 1
    assert found[0].last_seen == 42.0
    assert GRANT in found[0].allowed_types, \
        "a concurrent commit between merge and write was erased"

def test_commit_missing_disk_record_writes_full_record(tmp_path, monkeypatch):
    """A record dropped from the store file between load and commit has no
    baseline; commit must write the full record, never a partial one."""
    db = make_db(tmp_path, monkeypatch)
    db.add_item(make_client(client_id=1, api_key="k", name="sat",
                            allowed_types=[VOICE_SAT_DEFAULT]))
    assert db.commit()

    db_a = make_db(tmp_path, monkeypatch)
    stale = db_a.search_by_value("api_key", "k")[0]

    # the record leaves the store file after db_a loaded it
    store = tmp_path / "hivemind-core" / "clients.json"
    assert store.exists()
    store.write_text("{}")

    stale.last_seen = 123.0
    db_a.update_item(stale)
    assert db_a.commit()

    fresh = make_db(tmp_path, monkeypatch)
    found = fresh.search_by_value("api_key", "k")
    assert len(found) == 1
    rec = found[0]
    assert rec.api_key == "k", "the record was written back partial"
    assert rec.name == "sat"
    assert rec.allowed_types == [VOICE_SAT_DEFAULT]
    assert rec.last_seen == 123.0


def test_encrypted_store_stays_encrypted(tmp_path, monkeypatch):
    """A store opened with a password holds the PSK of every client. A
    commit must write the AES-GCM envelope, never the plain records, and
    the store must reload."""
    import json

    key = "0123456789abcdef"
    monkeypatch.setattr(hpm, "xdg_data_home", lambda: str(tmp_path))
    db = JsonDB(password=key)
    db.add_item(make_client(client_id=1, api_key="supersecret-key",
                            name="sat", password="the-psk",
                            allowed_types=[VOICE_SAT_DEFAULT]))
    assert db.commit()

    with open(db._db.path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    assert "supersecret-key" not in json.dumps(raw), \
        "the client store was written in clear text"
    assert "the-psk" not in json.dumps(raw)
    assert set(raw) == {"ciphertext", "tag", "nonce"}

    fresh = JsonDB(password=key)
    found = fresh.search_by_value("api_key", "supersecret-key")
    assert len(found) == 1
    assert found[0].password == "the-psk"
    assert VOICE_SAT_DEFAULT in found[0].allowed_types


def test_encrypted_store_merges_concurrent_grant(tmp_path, monkeypatch):
    """The re-read at commit time must decrypt, so the merge on an
    encrypted store keeps a concurrent consumer's grant."""
    key = "0123456789abcdef"
    monkeypatch.setattr(hpm, "xdg_data_home", lambda: str(tmp_path))
    db = JsonDB(password=key)
    db.add_item(make_client(client_id=1, api_key="k", name="sat",
                            allowed_types=[]))
    assert db.commit()

    stale = JsonDB(password=key)
    record = stale.search_by_value("api_key", "k")[0]

    granter = JsonDB(password=key)
    granted = granter.search_by_value("api_key", "k")[0]
    granted.allowed_types.append(GRANT)
    granter.update_item(granted)
    assert granter.commit()

    record.last_seen = 42.0
    stale.update_item(record)
    assert stale.commit()

    fresh = JsonDB(password=key)
    found = fresh.search_by_value("api_key", "k")
    assert len(found) == 1
    assert found[0].last_seen == 42.0
    assert GRANT in found[0].allowed_types


def test_commit_preserves_store_file_mode(tmp_path, monkeypatch):
    """The mode of an existing store file survives a commit."""
    db = make_db(tmp_path, monkeypatch)
    db.add_item(make_client(client_id=1, api_key="k", name="sat",
                            allowed_types=[]))
    assert db.commit()
    os.chmod(db._db.path, 0o644)

    client = db.search_by_value("api_key", "k")[0]
    client.last_seen = 7.0
    db.update_item(client)
    assert db.commit()

    assert oct(os.stat(db._db.path).st_mode & 0o777) == "0o644"


def test_iterate_mutate_update_writes_the_change(tmp_path, monkeypatch):
    """A caller that finds a client by iterating, mutates it in place and
    calls update_item must have its change written. hivemind-core's
    resolve_client (the allow-msg path) finds its client this way."""
    db = make_db(tmp_path, monkeypatch)
    db.add_item(make_client(client_id=1, api_key="k", name="sat",
                            allowed_types=[]))
    assert db.commit()

    cli = make_db(tmp_path, monkeypatch)
    for client in cli:
        if client.name == "sat":
            client.allowed_types.append(GRANT)
            cli.update_item(client)
            break
    assert cli.commit()

    fresh = make_db(tmp_path, monkeypatch)
    found = fresh.search_by_value("api_key", "k")
    assert len(found) == 1
    assert GRANT in found[0].allowed_types, \
        "a grant made through the iteration path was not written"
