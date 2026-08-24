"""Automatic 'moments': events found in the library without anyone tagging anything.

A moment is a burst of photography that hangs together in time, and usually in
place and company too — a party, a meetup, a night out. We look for gaps in the
timeline rather than fixed windows, so a three-hour hangout stays one moment and
two unrelated evenings on the same day stay separate.
"""
from datetime import timedelta

from . import fmt

GAP = timedelta(hours=4)        # quiet time that ends a moment
MIN_PHOTOS = 6                  # below this it is a snapshot, not an event
MIN_PEOPLE = 0                  # solo moments are allowed (scenery trips)


def _label(rows, people, worlds):
    """A human title: the world when it dominates, otherwise the company."""
    when = fmt.date_short(rows[0]["taken_at"])
    top_world = max(worlds.items(), key=lambda kv: kv[1])[0] if worlds else ""
    share = (worlds.get(top_world, 0) / len(rows)) if worlds else 0
    if top_world and share >= 0.6:
        return f"{top_world} · {when}"
    if people:
        top = sorted(people.items(), key=lambda kv: -kv[1])[:2]
        names = " & ".join(n for n, _c in top)
        return f"With {names} · {when}"
    return f"{when}"


def detect(rows, people_by_photo, min_photos=MIN_PHOTOS, gap=GAP):
    """rows: photo rows ordered by taken_at (needs id, taken_at, world_name, day).
    people_by_photo: {photo_id: [names]} with your own names already removed.
    -> list of dicts(title, ids, start, end, world, people, count)."""
    out = []
    cluster = []
    prev = None
    for r in rows:
        dt = fmt.parse_iso(r["taken_at"])
        if not dt:
            continue
        if prev is not None and (dt - prev) > gap:
            m = _finish(cluster, people_by_photo, min_photos)
            if m:
                out.append(m)
            cluster = []
        cluster.append(r)
        prev = dt
    m = _finish(cluster, people_by_photo, min_photos)
    if m:
        out.append(m)
    out.sort(key=lambda m: m["start"], reverse=True)
    return out


def _finish(cluster, people_by_photo, min_photos):
    if len(cluster) < min_photos:
        return None
    people, worlds = {}, {}
    for r in cluster:
        for n in people_by_photo.get(r["id"], ()):
            people[n] = people.get(n, 0) + 1
        w = r["world_name"]
        if w:
            worlds[w] = worlds.get(w, 0) + 1
    if len(people) < MIN_PEOPLE:
        return None
    top_world = max(worlds.items(), key=lambda kv: kv[1])[0] if worlds else ""
    return {
        "title": _label(cluster, people, worlds),
        "ids": [r["id"] for r in cluster],
        "start": cluster[0]["taken_at"],
        "end": cluster[-1]["taken_at"],
        "world": top_world,
        "people": sorted(people, key=lambda n: -people[n]),
        "count": len(cluster),
        "cover_id": cluster[len(cluster) // 2]["id"],
    }
