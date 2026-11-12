"""Offline tests for voice store edge cases."""
import json
import sys

sys.path.insert(0, ".")

from src.voice.store import LockStore, WhitelistStore


def test_jsonstore_read_invalid_json(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("{invalid json", encoding="utf-8")
    store = LockStore(p)
    assert store._data == {}


def test_jsonstore_read_non_dict(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("[1,2,3]", encoding="utf-8")
    store = LockStore(p)
    assert store._data == {}


def test_jsonstore_read_missing_file(tmp_path):
    store = LockStore(tmp_path / "nope.json")
    assert store._data == {}


def test_set_enforced_name_no_record(tmp_path):
    store = LockStore(tmp_path / "l.json")
    store.set_enforced_name(123, "name")  # no record -> no-op
    assert store.is_locked(123) is False


def test_records_skips_invalid(tmp_path):
    p = tmp_path / "l.json"
    # one valid, one with non-int key
    p.write_text(json.dumps({"1": {"channel_id": 1, "locked_at": "2026-01-01T00:00:00", "locked_by": None}, "x": {}}), encoding="utf-8")
    store = LockStore(p)
    recs = list(store.records())
    assert len(recs) == 1
    assert recs[0].channel_id == 1


def test_channel_ids_skips_invalid(tmp_path):
    p = tmp_path / "l.json"
    p.write_text(json.dumps({"1": {}, "abc": {}}), encoding="utf-8")
    store = LockStore(p)
    assert store.channel_ids() == {1}


def test_whitelist_entries_non_dict_value(tmp_path):
    p = tmp_path / "w.json"
    p.write_text(json.dumps({"1": {"username": "A"}, "2": "not-dict"}), encoding="utf-8")
    store = WhitelistStore(p)
    entries = store.entries()
    assert (1, "A") in entries
    # key 2: non-dict -> name ""
    assert (2, "") in entries


def test_whitelist_ids_skips_invalid(tmp_path):
    p = tmp_path / "w.json"
    p.write_text(json.dumps({"1": {}, "zz": {}}), encoding="utf-8")
    store = WhitelistStore(p)
    assert store.ids() == {1}


def test_lock_store_unlock_missing(tmp_path):
    store = LockStore(tmp_path / "l.json")
    assert store.unlock(999) is None


def test_whitelist_remove_missing(tmp_path):
    store = WhitelistStore(tmp_path / "w.json")
    assert store.remove(999) is False


def test_whitelist_remove_exists(tmp_path):
    store = WhitelistStore(tmp_path / "w.json")
    store.add(123, "Alice")
    assert store.remove(123) is True
    assert store.remove(123) is False
