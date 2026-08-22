"""Log parsing: the layer everything else in the app is built on top of."""
from datetime import datetime

from vrchronicle import vrclog

ISO = "%Y-%m-%dT%H:%M:%S"


# ---------------------------------------------------------------- instances

def test_instance_types_from_real_log_shapes():
    """Every descriptor shape observed in real VRChat logs."""
    cases = {
        "00474~private(usr_x)~canRequestInvite~region(eu)": ("invite+", "eu"),
        "00474~private(usr_x)~region(use)": ("invite", "use"),
        "12345~hidden(usr_x)~region(eu)": ("friends+", "eu"),
        "00812~region(eu)": ("public", "eu"),
        "99~group(grp_x)~groupAccessType(public)~region(use)": ("group", "use"),
        "99~group(grp_x)~groupAccessType(plus)~region(eu)": ("group+", "eu"),
        "99~group(grp_x)~groupAccessType(members)~region(eu)": ("group-members", "eu"),
        "77~friends(usr_x)~region(jp)": ("friends", "jp"),
    }
    for descriptor, expected in cases.items():
        assert vrclog.parse_instance(descriptor) == expected, descriptor


def test_instance_empty_descriptor_is_unknown_not_public():
    """No descriptor must not be mistaken for 'public' — that drives a privacy
    warning, and guessing wrong in that direction is the unsafe way to be wrong."""
    assert vrclog.parse_instance("") == ("", "")
    assert vrclog.parse_instance(None) == ("", "")


def test_private_instance_set_matches_labels():
    for key in vrclog.PRIVATE_INSTANCES:
        assert key in vrclog.INSTANCE_LABELS
    assert "public" not in vrclog.PRIVATE_INSTANCES
    assert "group" not in vrclog.PRIVATE_INSTANCES      # group-public is open


# ---------------------------------------------------------------- parse_log

SAMPLE = """\
2026.01.02 20:38:27 Debug      -  User Authenticated: YourName (usr_aaa)
2026.01.02 20:38:35 Debug      -  [Behaviour] Entering Room: Some World
2026.01.02 20:38:35 Debug      -  [Behaviour] Joining wrld_1111:007~hidden(usr_aaa)~region(eu)
2026.01.02 20:38:35 Debug      -  [Behaviour] Joining or Creating Room: Some World
2026.01.02 20:38:49 Debug      -  [Behaviour] Switching YourName to avatar Some Avatar
2026.01.02 20:38:50 Debug      -  [Behaviour] OnPlayerJoined YourName (usr_aaa)
2026.01.02 20:38:52 Debug      -  [Behaviour] OnPlayerJoined Someone Else (usr_bbb)
2026.01.02 20:50:00 Debug      -  [Behaviour] OnPlayerLeft Someone Else (usr_bbb)
2026.01.02 21:00:00 Debug      -  [Behaviour] Entering Room: Other World
2026.01.02 21:00:00 Debug      -  [Behaviour] Joining wrld_2222:009~region(use)
2026.01.02 21:00:10 Debug      -  [Behaviour] OnPlayerJoined Third Person (usr_ccc)
2026.01.02 21:30:00 Debug      -  [Behaviour] OnPlayerLeft Third Person (usr_ccc)
"""


def _parse(tmp_path, text=SAMPLE):
    p = tmp_path / "output_log_2026-01-02_20-00-00.txt"
    p.write_text(text, encoding="utf-8")
    return vrclog.parse_log(str(p))


def test_parse_log_splits_sessions_and_keeps_instance_type(tmp_path):
    sessions, auth, avatars = _parse(tmp_path)
    assert [s["world_id"] for s in sessions] == ["wrld_1111", "wrld_2222"]
    assert sessions[0]["world_name"] == "Some World"
    assert sessions[0]["instance_type"] == "friends+"
    assert sessions[0]["region"] == "eu"
    assert sessions[1]["instance_type"] == "public"
    assert auth == {"YourName"}


def test_parse_log_records_avatar_switches(tmp_path):
    _sessions, _auth, avatars = _parse(tmp_path)
    assert avatars == [("2026-01-02T20:38:49", "YourName", "Some Avatar")]


def test_parse_log_player_spans_close_on_leave(tmp_path):
    sessions, _auth, _avatars = _parse(tmp_path)
    spans = {name: (join, leave) for name, _uid, join, leave in sessions[0]["players"]}
    assert spans["Someone Else"] == ("2026-01-02T20:38:52", "2026-01-02T20:50:00")
    assert spans["YourName"][1] is None          # never left before the world change


def test_parse_log_unreadable_file_returns_three_values(tmp_path):
    """Callers unpack three values; the error path must not hand back two."""
    result = vrclog.parse_log(str(tmp_path / "does-not-exist.txt"))
    assert len(result) == 3
    assert result == ([], set(), [])


def test_parse_log_survives_truncated_final_line(tmp_path):
    sessions, _a, _v = _parse(tmp_path, SAMPLE + "2026.01.02 21:31:00 Debug      -  [Beh")
    assert len(sessions) == 2


# ---------------------------------------------------------------- matcher

def _matcher(tmp_path):
    sessions, _auth, avatars = _parse(tmp_path)
    for i, s in enumerate(sessions, start=1):
        s["id"] = i
    return vrclog.SessionMatcher(sessions, [(at, av) for at, _who, av in avatars])


def test_matcher_places_a_photo_in_the_right_session(tmp_path):
    m = _matcher(tmp_path)
    sid, wid, wname, players, itype, region = m.match(datetime(2026, 1, 2, 20, 45, 0))
    assert (sid, wid, itype, region) == (1, "wrld_1111", "friends+", "eu")
    assert {n for n, _u in players} == {"YourName", "Someone Else"}


def test_matcher_excludes_someone_who_already_left(tmp_path):
    m = _matcher(tmp_path)
    _sid, _wid, _wn, players, _it, _rg = m.match(datetime(2026, 1, 2, 20, 55, 0))
    assert {n for n, _u in players} == {"YourName"}


def test_matcher_returns_none_long_after_the_log_ends(tmp_path):
    m = _matcher(tmp_path)
    assert m.match(datetime(2026, 1, 3, 12, 0, 0)) is None


def test_matcher_returns_none_before_any_session(tmp_path):
    m = _matcher(tmp_path)
    assert m.match(datetime(2026, 1, 1, 0, 0, 0)) is None


def test_avatar_at_uses_the_switch_in_effect(tmp_path):
    m = _matcher(tmp_path)
    assert m.avatar_at(datetime(2026, 1, 2, 20, 45, 0)) == "Some Avatar"
    assert m.avatar_at(datetime(2026, 1, 2, 20, 38, 0)) is None   # before any switch


def test_avatar_at_goes_stale_rather_than_guessing(tmp_path):
    """A switch from a fortnight ago says nothing about today's photo."""
    m = _matcher(tmp_path)
    assert m.avatar_at(datetime(2026, 1, 20, 12, 0, 0)) is None
