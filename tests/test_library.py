"""Moment detection, filename parsing, formatting, and the database migration."""
import sqlite3
from datetime import datetime, timedelta

import pytest

from vrchronicle import fmt, imaging, moments
from vrchronicle.db import Database, PhotoFilter


# ---------------------------------------------------------------- filenames

def test_shot_time_from_current_and_legacy_filenames():
    got = imaging.parse_shot_time("VRChat_2026-08-21_18-52-08.986_3840x2160.png")
    assert got == datetime(2026, 8, 21, 18, 52, 8, 986000)
    old = imaging.parse_shot_time("VRChat_1920x1080_2021-03-04_05-06-07.089.png")
    assert old == datetime(2021, 3, 4, 5, 6, 7, 89000)


def test_shot_time_none_for_unrelated_names():
    assert imaging.parse_shot_time("holiday.png") is None
    assert imaging.parse_shot_time("VRChat_2026-13-45_99-99-99.000.png") is None


def test_dhash_distance_is_symmetric_and_bounded():
    assert imaging.dhash_distance("0" * 16, "0" * 16) == 0
    assert imaging.dhash_distance("f" * 16, "0" * 16) == 64
    assert imaging.dhash_distance("abc", None) == 64      # unusable input


# ---------------------------------------------------------------- formatting

def test_human_size_reads_naturally():
    assert fmt.human_size(0) == "0 B"
    assert fmt.human_size(1536) == "1.5 KB"
    assert fmt.human_size(None) == "0 B"


def test_plural_and_month_labels():
    assert fmt.plural(1, "photo") == "photo"
    assert fmt.plural(2, "photo") == "photos"
    assert fmt.month_label("2026-08") == "Aug '26"
    assert fmt.month_label("nonsense") == "nonsense"


def test_day_label_marks_today_and_yesterday():
    from datetime import date
    today = date(2026, 8, 22)
    assert fmt.day_label("2026-08-22", today).startswith("Today · ")
    assert fmt.day_label("2026-08-21", today).startswith("Yesterday · ")
    assert not fmt.day_label("2026-08-01", today).startswith(("Today", "Yesterday"))


# ---------------------------------------------------------------- moments

def _rows(start, count, world="Some World", step_minutes=3, first_id=1):
    out = []
    for i in range(count):
        t = start + timedelta(minutes=i * step_minutes)
        out.append({"id": first_id + i, "taken_at": t.strftime("%Y-%m-%dT%H:%M:%S"),
                    "day": t.strftime("%Y-%m-%d"), "world_name": world})
    return out


def test_a_quiet_gap_starts_a_new_moment():
    evening = _rows(datetime(2026, 5, 1, 20, 0), 8)
    next_day = _rows(datetime(2026, 5, 2, 21, 0), 7, world="Other World", first_id=100)
    found = moments.detect(evening + next_day, {})
    assert len(found) == 2
    assert {m["world"] for m in found} == {"Some World", "Other World"}


def test_a_long_hangout_stays_one_moment():
    rows = _rows(datetime(2026, 5, 1, 20, 0), 40, step_minutes=5)   # 3h20m straight
    found = moments.detect(rows, {})
    assert len(found) == 1
    assert found[0]["count"] == 40


def test_a_handful_of_shots_is_not_an_event():
    assert moments.detect(_rows(datetime(2026, 5, 1, 20, 0), 3), {}) == []


def test_moment_is_titled_after_the_company_when_no_world_dominates():
    rows = _rows(datetime(2026, 5, 1, 20, 0), 8)
    for i, r in enumerate(rows):
        r["world_name"] = f"World {i}"          # no world holds 60%
    people = {r["id"]: ["Nova", "Pixel"] for r in rows}
    found = moments.detect(rows, people)
    assert found[0]["title"].startswith("With ")
    assert "Nova" in found[0]["title"]


def test_moment_is_titled_after_the_world_when_one_dominates():
    rows = _rows(datetime(2026, 5, 1, 20, 0), 8)
    found = moments.detect(rows, {r["id"]: ["Nova"] for r in rows})
    assert found[0]["title"].startswith("Some World · ")


def test_moments_tolerate_missing_timestamps_and_worlds():
    rows = _rows(datetime(2026, 5, 1, 20, 0), 8)
    rows[2]["taken_at"] = None
    rows[3]["world_name"] = None
    found = moments.detect(rows, {})
    assert len(found) == 1
    assert found[0]["count"] == 7          # the unparseable row is skipped, not fatal


def test_moments_on_an_empty_library():
    assert moments.detect([], {}) == []


# ---------------------------------------------------------------- database

def test_migration_adds_columns_to_an_older_library(tmp_path):
    """A library made by an earlier version must open, not crash."""
    db_path = tmp_path / "old.db"
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE photos(
          id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, folder TEXT,
          filename TEXT, taken_at TEXT, day TEXT, width INTEGER DEFAULT 0,
          height INTEGER DEFAULT 0, filesize INTEGER DEFAULT 0, mtime REAL DEFAULT 0,
          world_id TEXT, world_name TEXT, meta_source TEXT DEFAULT 'none',
          favorite INTEGER DEFAULT 0, luma REAL, dhash TEXT,
          scanned INTEGER DEFAULT 0, missing INTEGER DEFAULT 0);
        CREATE TABLE sessions(
          id INTEGER PRIMARY KEY, log_file TEXT, world_id TEXT, world_name TEXT,
          start_at TEXT, end_at TEXT);
        INSERT INTO photos(path, filename, taken_at, day, filesize)
        VALUES('C:\\old\\a.png', 'a.png', '2025-01-01T10:00:00', '2025-01-01', 10);
    """)
    con.commit()
    con.close()

    db = Database(str(db_path))
    cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(photos)")}
    assert {"avatar_name", "session_id", "instance_type"} <= cols
    assert len(db.query_photos(PhotoFilter())) == 1
    db.close()

    Database(str(db_path)).close()          # opening twice must also be fine


def test_filters_narrow_the_library(tmp_path):
    db = Database(str(tmp_path / "f.db"))
    db.upsert_photos([
        {"path": "a.png", "folder": ".", "filename": "a.png",
         "taken_at": "2026-01-01T10:00:00", "day": "2026-01-01",
         "filesize": 10, "mtime": 1},
        {"path": "b.png", "folder": ".", "filename": "b.png",
         "taken_at": "2026-02-02T10:00:00", "day": "2026-02-02",
         "filesize": 20, "mtime": 2},
    ])
    assert len(db.query_photos(PhotoFilter())) == 2
    assert len(db.query_photos(PhotoFilter(day="2026-01-01"))) == 1

    ids = [r["id"] for r in db.query_photos(PhotoFilter())]
    db.set_favorite(ids[:1], True)
    assert len(db.query_photos(PhotoFilter(favorites=True))) == 1
    db.close()


def test_search_treats_like_wildcards_as_literal_text(tmp_path):
    db = Database(str(tmp_path / "s.db"))
    db.upsert_photos([
        {"path": "a.png", "folder": ".", "filename": "100% cool.png",
         "taken_at": "2026-01-01T10:00:00", "day": "2026-01-01",
         "filesize": 1, "mtime": 1},
        {"path": "b.png", "folder": ".", "filename": "plain.png",
         "taken_at": "2026-01-02T10:00:00", "day": "2026-01-02",
         "filesize": 1, "mtime": 2},
    ])
    # '%' and '_' are LIKE wildcards: typed by a user they must match themselves
    assert len(db.query_photos(PhotoFilter(text="%"))) == 1
    assert len(db.query_photos(PhotoFilter(text="100%"))) == 1
    assert db.query_photos(PhotoFilter(text="zzz")) == []
    db.close()
