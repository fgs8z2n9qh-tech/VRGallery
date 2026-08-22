"""VRChat output_log parsing: world sessions + who was in the instance when.

Log lines look like:
  2026.01.02 20:38:27 Debug      -  User Authenticated: YourName (usr_...)
  2026.01.02 20:38:35 Debug      -  [Behaviour] Entering Room: Some World
  2026.01.02 20:38:35 Debug      -  [Behaviour] Joining wrld_1234...:00474~private(...)~region(eu)
  2026.01.02 20:38:35 Debug      -  [Behaviour] Joining or Creating Room: Some World
  2026.01.02 20:38:50 Debug      -  [Behaviour] OnPlayerJoined SomeoneElse (usr_...)
  2026.01.02 20:39:17 Debug      -  [Behaviour] OnPlayerLeft SomeoneElse (usr_...)
  2026.01.02 20:38:49 Debug      -  [Behaviour] Switching YourName to avatar Some Avatar
"""
import glob
import os
import re
from bisect import bisect_right
from datetime import datetime, timedelta

from . import paths

RE_TS = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})")
RE_AUTH = re.compile(r"User Authenticated: (.+?) \(usr_[0-9a-f-]+\)")
RE_ENTER = re.compile(r"\[Behaviour\] Entering Room: (.*)$")
RE_JOINING = re.compile(r"\[Behaviour\] Joining (wrld_[0-9a-fA-F-]+)")
RE_JOIN_ROOM = re.compile(r"\[Behaviour\] Joining or Creating Room: (.*)$")
RE_PJOIN = re.compile(r"\[Behaviour\] OnPlayerJoined (.+?)(?:\s+\((usr_[0-9a-f-]+)\))?\s*$")
RE_PLEFT = re.compile(r"\[Behaviour\] OnPlayerLeft (.+?)(?:\s+\((usr_[0-9a-f-]+)\))?\s*$")
RE_SWITCH = re.compile(r"\[Behaviour\] Switching (.+?) to avatar (.+?)\s*$")
# the instance descriptor that follows the world id, e.g.
#   :00474~private(usr_…)~canRequestInvite~region(eu)
#   :12345~group(grp_…)~groupAccessType(public)~region(use)
#   :00812~region(eu)                                   <- public
RE_INSTANCE = re.compile(r"\[Behaviour\] Joining wrld_[0-9a-fA-F-]+:(\S+)")
RE_REGION = re.compile(r"~region\(([a-z]+)\)")
RE_GROUP_ACCESS = re.compile(r"~groupAccessType\(([a-zA-Z]+)\)")

# machine value -> what VRChat calls it in the UI
INSTANCE_LABELS = {
    "public": "Public",
    "friends+": "Friends+",
    "friends": "Friends",
    "invite+": "Invite+",
    "invite": "Invite",
    "group": "Group",
    "group+": "Group+",
    "group-members": "Group members",
    "": "Unknown",
}
# which ones mean "not everyone could have seen this"
PRIVATE_INSTANCES = {"friends+", "friends", "invite+", "invite", "group-members"}


def parse_instance(descriptor):
    """-> (instance_type, region). `descriptor` is everything after 'wrld_…:'."""
    if not descriptor:
        return "", ""
    region = ""
    m = RE_REGION.search(descriptor)
    if m:
        region = m.group(1)
    if "~group(" in descriptor:
        access = ""
        g = RE_GROUP_ACCESS.search(descriptor)
        if g:
            access = g.group(1).lower()
        if access == "public":
            return "group", region
        if access == "plus":
            return "group+", region
        return "group-members", region
    if "~private(" in descriptor:
        return ("invite+" if "~canRequestInvite" in descriptor else "invite"), region
    if "~hidden(" in descriptor:
        return "friends+", region
    if "~friends(" in descriptor:
        return "friends", region
    return "public", region

ISO = "%Y-%m-%dT%H:%M:%S"

# Bump whenever parse_log() starts extracting something new: a library upgraded
# from an older version has its logs marked "already read", so they must be
# re-parsed or the new data would only ever appear for future sessions.
PARSER_VERSION = 3


def find_logs():
    d = paths.vrchat_log_dir()
    if not os.path.isdir(d):
        return []
    files = glob.glob(os.path.join(d, "output_log*.txt"))
    files.sort(key=lambda p: os.path.getmtime(p))
    return files


def parse_log(path):
    """-> (sessions, auth_names, avatar_events). Sessions are dicts:
       {world_id, world_name, start, end, players: [(name, uid, join_iso, leave_iso|None)]}
    avatar_events is [(iso, player_name, avatar_name)] across the whole log.
    Times are naive-local ISO strings (same clock as the screenshot filenames)."""
    sessions = []
    auth_names = set()
    avatar_events = []
    cur = None            # open session dict
    cur_players = None    # name -> list of [uid, join_iso, leave_iso|None]
    pending_name = None
    last_ts = None

    def close(end_iso):
        nonlocal cur, cur_players
        if cur is None:
            return
        cur["end"] = end_iso or cur["start"]
        players = []
        for name, spans in cur_players.items():
            for uid, j, l in spans:
                players.append((name, uid, j, l))
        cur["players"] = players
        sessions.append(cur)
        cur = None
        cur_players = None

    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return [], set(), []          # same arity as the normal return
    with f:
        for line in f:
            m = RE_TS.match(line)
            if m:
                last_ts = "%s-%s-%sT%s:%s:%s" % m.groups()
            if "User Authenticated:" in line:
                a = RE_AUTH.search(line)
                if a:
                    auth_names.add(a.group(1).strip())
                continue
            if "[Behaviour]" not in line:
                continue
            if "Entering Room:" in line:
                e = RE_ENTER.search(line)
                if e:
                    pending_name = e.group(1).strip() or None
                continue
            if "Joining wrld_" in line:
                j = RE_JOINING.search(line)
                if j and last_ts:
                    close(last_ts)
                    d = RE_INSTANCE.search(line)
                    itype, region = parse_instance(d.group(1) if d else "")
                    cur = {"world_id": j.group(1), "world_name": pending_name,
                           "start": last_ts, "end": None,
                           "instance_type": itype, "region": region}
                    cur_players = {}
                    pending_name = None
                continue
            if "Joining or Creating Room:" in line:
                j = RE_JOIN_ROOM.search(line)
                if j and cur is not None:
                    name = j.group(1).strip()
                    if name:
                        cur["world_name"] = name
                continue
            if "OnPlayerJoined " in line:
                p = RE_PJOIN.search(line)
                if p and cur is not None and last_ts:
                    name = p.group(1).strip()
                    if name:
                        cur_players.setdefault(name, []).append(
                            [p.group(2), last_ts, None])
                continue
            if "OnPlayerLeft " in line:
                p = RE_PLEFT.search(line)
                if p and cur is not None and last_ts:
                    name = p.group(1).strip()
                    spans = cur_players.get(name)
                    if spans and spans[-1][2] is None:
                        spans[-1][2] = last_ts
                continue
            if " to avatar " in line and "Switching " in line:
                p = RE_SWITCH.search(line)
                if p and last_ts:
                    who, av = p.group(1).strip(), p.group(2).strip()
                    if who and av:
                        avatar_events.append((last_ts, who, av))
                continue
    close(last_ts)
    for s in sessions:
        if not s["world_name"]:
            s["world_name"] = s["world_id"][:13] + "…"
    return sessions, auth_names, avatar_events


class SessionMatcher:
    """Answers: which world, which people and which avatar for a photo timestamp."""

    JOIN_MARGIN = timedelta(seconds=90)     # photo just after the log's last line
    PLAYER_PAD = timedelta(seconds=2)
    AVATAR_STALE = timedelta(days=7)        # don't trust an ancient switch event

    def __init__(self, sessions, avatar_events=()):
        parsed = []
        for s in sessions:
            try:
                st = datetime.strptime(s["start"], ISO)
                en = datetime.strptime(s["end"], ISO) if s["end"] else st
            except (ValueError, TypeError):
                continue
            players = []
            for name, uid, j, l in s["players"]:
                try:
                    jd = datetime.strptime(j, ISO)
                except (ValueError, TypeError):
                    continue
                ld = None
                if l:
                    try:
                        ld = datetime.strptime(l, ISO)
                    except ValueError:
                        ld = None
                players.append((name, uid, jd, ld))
            parsed.append((st, en, s.get("id"), s["world_id"], s["world_name"], players,
                           s.get("instance_type") or "", s.get("region") or ""))
        parsed.sort(key=lambda t: t[0])
        self._sessions = parsed
        self._starts = [t[0] for t in parsed]

        av = []
        for at, avatar in avatar_events:
            try:
                av.append((datetime.strptime(at[:19], ISO), avatar))
            except (ValueError, TypeError):
                continue
        av.sort(key=lambda t: t[0])
        self._avatars = av
        self._avatar_times = [t[0] for t in av]

    def match(self, dt):
        """-> (session_id, world_id, world_name, [(name, uid)], instance_type, region)
        or None."""
        if not self._sessions:
            return None
        i = bisect_right(self._starts, dt) - 1
        if i < 0:
            return None
        st, en, sid, wid, wname, players, itype, region = self._sessions[i]
        if dt > en + self.JOIN_MARGIN:
            return None
        seen = {}
        for name, uid, jd, ld in players:
            if jd - self.PLAYER_PAD <= dt and (ld is None or ld + self.PLAYER_PAD >= dt):
                seen.setdefault(name, uid)
        return sid, wid, wname, sorted(seen.items()), itype, region

    def avatar_at(self, dt):
        """The local user's avatar name at that moment, or None."""
        if not self._avatars:
            return None
        i = bisect_right(self._avatar_times, dt) - 1
        if i < 0:
            return None
        when, name = self._avatars[i]
        if dt - when > self.AVATAR_STALE:
            return None
        return name
