"""End-to-end: the real ``hivemind-core allow-msg`` CLI against a JSON store.

The CLI resolves its client with ``hivemind_core.scripts.resolve_client``,
which iterates the database (``for client in db``) and then mutates the
``Client`` it got back in place before calling ``update_item``. A merge that
takes its baseline from the already-mutated record reads the grant as
untouched and keeps the on-disk value, so the CLI prints success and writes
nothing. The unit suite cannot see this: it reaches the store through
``search_by_value``.

Skipped when hivemind-core is not installed.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

hivemind_core = pytest.importorskip("hivemind_core")

GRANT = "recognizer_loop:utterance"


def _cli(*args, env):
    """Run the hivemind-core CLI, preferring the console script."""
    exe = shutil.which("hivemind-core")
    cmd = [exe, *args] if exe else [sys.executable, "-m",
                                    "hivemind_core.scripts", *args]
    return subprocess.run(cmd, env=env, capture_output=True, text=True,
                          timeout=120)


@pytest.fixture
def cli_env(tmp_path):
    """A fresh XDG home holding an empty clients.json.

    ``hivemind_core.config._default_database`` picks the JSON backend only
    while a clients.json exists and no clients.db does, so the empty file is
    what selects the backend under test.
    """
    data_home = tmp_path / "data"
    store_dir = data_home / "hivemind-core"
    store_dir.mkdir(parents=True)
    (store_dir / "clients.json").write_text("{}", encoding="utf-8")
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = str(data_home)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    return env, store_dir / "clients.json"


def test_allow_msg_cli_writes_the_grant(cli_env):
    """add-client, then allow-msg, then read the store back: the grant is on
    disk. Fails before the __iter__ fix, where the CLI printed success and
    wrote nothing."""
    env, store = cli_env

    added = _cli("add-client", "--name", "sat1",
                 "--access-key", "GATEKEY34GATEKEY34GATEKEY34x",
                 "--password", "T4lus-Correct-Horse-9912", env=env)
    assert added.returncode == 0, added.stderr or added.stdout

    record = json.loads(store.read_text(encoding="utf-8"))
    assert record, "add-client wrote no client to the JSON store"
    client_id = sorted(record)[0]

    granted = _cli("allow-msg", GRANT, client_id, env=env)
    assert granted.returncode == 0, granted.stderr or granted.stdout

    after = json.loads(store.read_text(encoding="utf-8"))
    allowed = after[client_id].get("allowed_types") or []
    assert GRANT in allowed, (
        f"allow-msg exited 0 and said {granted.stdout.strip()!r}, "
        f"but the store holds allowed_types={allowed!r}")
