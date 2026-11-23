from datetime import UTC, datetime

from app.krawl.service import counter_bucket_id, should_ban


def test_probe_threshold_requires_repeated_hits() -> None:
    assert not should_ban(1, 3)
    assert not should_ban(2, 3)
    assert should_ban(3, 3)
    assert should_ban(4, 3)


def test_counter_bucket_is_stable_within_window_and_changes_after() -> None:
    first = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    same_window = datetime(2026, 11, 23, 12, 9, tzinfo=UTC)
    next_window = datetime(2026, 11, 23, 12, 10, tzinfo=UTC)

    assert counter_bucket_id("abc", first, 600) == counter_bucket_id("abc", same_window, 600)
    assert counter_bucket_id("abc", first, 600) != counter_bucket_id("abc", next_window, 600)
