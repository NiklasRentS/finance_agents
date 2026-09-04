"""Tests for the disk cache."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.infra.cache import DiskCache, cache_key


class TestCacheKey:
    def test_same_inputs_produce_same_key(self) -> None:
        assert cache_key("sec", "AAPL") == cache_key("sec", "AAPL")

    def test_different_inputs_produce_different_keys(self) -> None:
        assert cache_key("sec", "AAPL") != cache_key("sec", "MSFT")

    def test_part_boundaries_are_unambiguous(self) -> None:
        assert cache_key("ab", "c") != cache_key("a", "bc")


class TestDiskCache:
    def test_roundtrip(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path)
        cache.set("k1", '{"revenue": 1}', timedelta(hours=1))
        assert cache.get("k1") == '{"revenue": 1}'

    def test_missing_key_returns_none(self, tmp_path: Path) -> None:
        assert DiskCache(tmp_path).get("absent") is None

    def test_expired_entry_is_not_returned(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path)
        cache.set("k1", "stale", timedelta(seconds=-1))
        assert cache.get("k1") is None

    def test_none_ttl_disables_storage(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path)
        cache.set("k1", "value", None)
        assert cache.get("k1") is None

    def test_disabled_cache_stores_nothing(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path, enabled=False)
        cache.set("k1", "value", timedelta(hours=1))
        assert cache.get("k1") is None
        assert not cache.enabled

    def test_corrupted_entry_is_treated_as_miss(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path)
        cache.set("k1", "value", timedelta(hours=1))
        corrupted = next(tmp_path.rglob("*.json"))
        corrupted.write_text("not json", encoding="utf-8")
        assert cache.get("k1") is None

    def test_clear_removes_entries(self, tmp_path: Path) -> None:
        cache = DiskCache(tmp_path)
        cache.set("k1", "a", timedelta(hours=1))
        cache.set("k2", "b", timedelta(hours=1))
        assert cache.clear() == 2
        assert cache.get("k1") is None
