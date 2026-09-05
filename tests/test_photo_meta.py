"""Metadata VRChat and VRCX embed in a screenshot's PNG.

Asked for in issue #1: VRChat's own metadata names the photographer and the
world, and VRCX's carries the instance type. Both were being partly thrown away
-- the old reader kept the world and the players and dropped the rest.

Measured on the real library before writing any of this: of the 500 newest
photos, 472 carried VRCX metadata, every one of them with an author and an
instance id. None carried VRChat's own, because VRCX is doing the writing on
that machine -- which is exactly why the VRChat format is exercised here with a
file built to its documented shape rather than trusted to look after itself.
"""
import json
import os

import pytest

pytest.importorskip("PIL")

from PIL import Image, PngImagePlugin

from vrgallery import imaging, vrclog

VRCHAT = {
    "application": "VRChat", "version": 1,
    "author": {"id": "usr_author", "displayName": "Photographer"},
    "world": {"name": "The Great Pug", "id": "wrld_pug",
              "instanceId": "wrld_pug:41234~group(grp_x)~groupAccessType(plus)~region(use)"},
    "players": [{"id": "usr_a", "displayName": "Alice", "x": 1.0, "y": 0.0, "z": 2.0},
                {"id": "usr_b", "displayName": "Bob"}],
}

VRCX = {
    "application": "VRCX", "version": 1,
    "author": {"id": "usr_me", "displayName": "Erik_21"},
    "world": {"name": "A Simple Fishing World", "id": "wrld_fish",
              "instanceId": "wrld_fish:51899~hidden(usr_friend)~region(eu)"},
    "players": [{"id": "usr_friend", "displayName": "RexiRose"}],
}


def _png(tmp_path, payload, key="Description", name="shot.png"):
    info = PngImagePlugin.PngInfo()
    info.add_text(key, payload if isinstance(payload, str) else json.dumps(payload))
    path = tmp_path / name
    Image.new("RGB", (8, 8), (20, 30, 40)).save(path, pnginfo=info)
    return str(path)


def _read(tmp_path, payload, **kw):
    return imaging.read_meta(_png(tmp_path, payload, **kw))


# ------------------------------------------------------- VRChat's own format

def test_vrchat_metadata_names_the_photographer_and_the_world(tmp_path):
    m = _read(tmp_path, VRCHAT)
    assert m is not None, "VRChat's own metadata was not read at all"
    assert m["source"] == "vrchat"
    assert m["author_name"] == "Photographer" and m["author_id"] == "usr_author"
    assert m["world_name"] == "The Great Pug" and m["world_id"] == "wrld_pug"
    assert m["players"] == [("Alice", "usr_a"), ("Bob", "usr_b")]


def test_the_instance_type_comes_out_of_the_instance_id(tmp_path):
    """Which is the other half of the request, and the only way to know it for
    a photo whose session VRChat has already deleted the log for."""
    assert _read(tmp_path, VRCHAT)["instance_type"] == "group+"
    assert _read(tmp_path, VRCHAT)["region"] == "use"


@pytest.mark.parametrize("descriptor,expected", [
    ("wrld_x:1~region(eu)", "public"),
    ("wrld_x:1~friends(usr_a)~region(eu)", "friends"),
    ("wrld_x:1~hidden(usr_a)~region(eu)", "friends+"),
    ("wrld_x:1~private(usr_a)~region(jp)", "invite"),
    ("wrld_x:1~private(usr_a)~canRequestInvite~region(jp)", "invite+"),
    ("wrld_x:1~group(grp_a)~groupAccessType(public)", "group"),
    ("wrld_x:1~group(grp_a)~groupAccessType(plus)", "group+"),
    ("wrld_x:1~group(grp_a)~groupAccessType(members)", "group-members"),
])
def test_every_instance_type_is_recognised(tmp_path, descriptor, expected):
    payload = json.loads(json.dumps(VRCHAT))
    payload["world"]["instanceId"] = descriptor
    assert _read(tmp_path, payload)["instance_type"] == expected


def test_the_photo_and_the_logs_read_an_instance_the_same_way(tmp_path):
    """Two ways to learn the same fact must not drift apart, so the photo
    parser hands the descriptor to the log parser rather than repeating it."""
    desc = "1~private(usr_a)~canRequestInvite~region(jp)"
    payload = json.loads(json.dumps(VRCHAT))
    payload["world"]["instanceId"] = "wrld_x:" + desc
    from_photo = _read(tmp_path, payload)
    from_log = vrclog.parse_instance(desc)
    assert (from_photo["instance_type"], from_photo["region"]) == from_log


# ------------------------------------------------------------- VRCX's format

def test_vrcx_metadata_reads_the_same_way(tmp_path):
    m = _read(tmp_path, VRCX)
    assert m["source"] == "vrcx"
    assert m["author_name"] == "Erik_21"
    assert m["instance_type"] == "friends+" and m["region"] == "eu"
    assert m["players"] == [("RexiRose", "usr_friend")]


def test_the_writer_is_reported_so_the_two_can_be_told_apart(tmp_path):
    assert _read(tmp_path, VRCHAT)["source"] == "vrchat"
    assert _read(tmp_path, VRCX)["source"] == "vrcx"


# ------------------------------------------------------------------- edges

def test_a_photo_with_no_metadata_reads_as_nothing(tmp_path):
    path = tmp_path / "plain.png"
    Image.new("RGB", (8, 8)).save(path)
    assert imaging.read_meta(str(path)) is None


def test_junk_in_a_text_chunk_does_not_raise(tmp_path):
    for junk in ("not json at all", "{", '{"application": "VRChat"', "[]", "{}"):
        assert _read(tmp_path, junk) is None or isinstance(_read(tmp_path, junk), dict)


def test_a_missing_file_reads_as_nothing():
    assert imaging.read_meta(r"C:\no\such\file.png") is None


def test_metadata_without_an_instance_id_still_gives_the_world(tmp_path):
    """Older VRCX builds wrote no instanceId, and blanking a photo's instance
    type because of that would lose what the logs had already worked out."""
    payload = json.loads(json.dumps(VRCX))
    payload["world"].pop("instanceId")
    m = _read(tmp_path, payload)
    assert m["world_name"] == "A Simple Fishing World"
    assert m["instance_type"] == "" and m["region"] == ""


def test_the_old_three_value_reader_still_works(tmp_path):
    with Image.open(_png(tmp_path, VRCX)) as im:
        wid, wname, players = imaging.parse_vrcx_text(getattr(im, "text", {}))
    assert wid == "wrld_fish" and wname == "A Simple Fishing World"
    assert players == [("RexiRose", "usr_friend")]


def test_the_version_is_bumped_so_old_libraries_are_re_read():
    """A library indexed before this existed has to have its photos read again,
    or the photographer and instance stay missing until each file changes."""
    assert imaging.META_VERSION >= 2


def test_every_region_code_the_parser_can_return_has_a_name():
    """The lightbox looks these up by name; a missing one raised inside a slot,
    which is how a Qt app dies with no traceback."""
    for code in ("eu", "us", "use", "usw", "jp"):
        assert code in vrclog.REGION_NAMES
    from vrgallery import pages
    assert pages.REGION_NAMES is vrclog.REGION_NAMES


# ------------------------------------------------- the file beats the log

def _library(tmp_path):
    from vrgallery import paths
    from vrgallery.db import Database
    paths.set_appdir(str(tmp_path / "lib"))
    paths.ensure_dirs()
    db = Database()
    db.upsert_photos([{
        "path": str(tmp_path / "a.png"), "folder": str(tmp_path),
        "filename": "VRChat_2026-03-01_12-00-00.000.png",
        "taken_at": "2026-03-01T12:00:00", "day": "2026-03-01",
        "filesize": 10, "mtime": 1.0,
    }])
    pid = db._conn.execute("SELECT id FROM photos LIMIT 1").fetchone()["id"]
    return db, pid


def test_what_the_photo_says_beats_what_the_log_inferred(tmp_path):
    """VRChat deletes its logs after a few sessions, so a photo whose session is
    gone gets an EMPTY instance from log correlation -- while the file itself
    still knows. Applied in the wrong order that empty answer won, and 1900
    photos came out of a real index pass with 112 instance types instead of 814.
    """
    db, pid = _library(tmp_path)
    db.apply_log_matches([{"id": pid, "session_id": None, "avatar": None,
                           "world_id": None, "world_name": None, "source": "log",
                           "instance_type": "", "region": "", "players": []}])
    db.set_meta_photo(pid, {"world_id": "wrld_x", "world_name": "Somewhere",
                            "source": "vrcx", "players": [],
                            "author_name": "Erik_21", "author_id": "usr_me",
                            "instance_type": "friends+", "region": "eu"})
    row = db._conn.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
    assert row["instance_type"] == "friends+" and row["region"] == "eu"
    assert row["author_name"] == "Erik_21"
    db.close()


def test_metadata_without_an_instance_leaves_the_logs_answer_alone(tmp_path):
    """The other direction: an older VRCX wrote no instanceId, and blanking what
    log correlation had worked out would be a straight loss."""
    db, pid = _library(tmp_path)
    db.apply_log_matches([{"id": pid, "session_id": None, "avatar": None,
                           "world_id": None, "world_name": None, "source": "log",
                           "instance_type": "group", "region": "use", "players": []}])
    db.set_meta_photo(pid, {"world_id": "wrld_x", "world_name": "Somewhere",
                            "source": "vrcx", "players": [], "instance_type": "",
                            "region": "", "author_name": None, "author_id": None})
    row = db._conn.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()
    assert row["instance_type"] == "group" and row["region"] == "use"
    db.close()


def test_the_re_read_sweep_runs_after_the_log_matching():
    """Source order, because that IS the bug: apply_log_matches writes
    instance_type from the session, so a sweep placed before it is overwritten.
    """
    import inspect
    from vrgallery import scanner
    body = inspect.getsource(scanner.IndexWorker._run)
    sweep = body.index("photo_meta_version")
    last_match = body.rindex("apply_log_matches")
    assert sweep > last_match, "the metadata sweep runs before log matching again"
