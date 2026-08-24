"""Headless index test against the real photo folder + logs, into a scratch DB."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QCoreApplication

from vrgallery import db as adb, scanner
from vrgallery.config import Config

SCRATCH = os.path.join(os.environ.get("TEMP", "."), "vrgallery_selftest.db")
for suffix in ("", "-wal", "-shm"):
    p = SCRATCH + suffix
    if os.path.exists(p):
        os.remove(p)

app = QCoreApplication([])
cfg = Config()
print("folders:", cfg.folders)
database = adb.Database(SCRATCH)
bridge = scanner.Bridge()
bridge.index_progress.connect(lambda t, a, b: print(f"  [{t}] {a}/{b}"))
bridge.toast.connect(lambda t, k: print("TOAST:", k, t))

done = {}
bridge.index_done.connect(lambda s: done.update(s))

w = scanner.IndexWorker(database, cfg, bridge)
t0 = time.time()
w.run()  # synchronous on purpose
print(f"\nindex took {time.time()-t0:.1f}s")
print("done stats:", {k: v for k, v in done.items() if k != "auth"})
print("auth names:", done.get("auth"))

c = database._conn
tot = c.execute("SELECT COUNT(*) c FROM photos WHERE missing=0").fetchone()["c"]
print(f"\nphotos: {tot}")
for r in c.execute("SELECT meta_source, COUNT(*) c FROM photos WHERE missing=0 "
                   "GROUP BY meta_source"):
    print(f"  source {r['meta_source']}: {r['c']} ({100.0*r['c']/tot:.1f}%)")

print("\n--- sessions & avatars (the new bits) ---")
print("sessions parsed:", c.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"])
print("avatar events:  ", c.execute("SELECT COUNT(*) c FROM avatar_events").fetchone()["c"])
linked = c.execute("SELECT COUNT(*) c FROM photos WHERE session_id IS NOT NULL").fetchone()["c"]
print(f"photos linked to a session: {linked} ({100.0*linked/tot:.1f}%)")
withav = c.execute("SELECT COUNT(*) c FROM photos WHERE avatar_name IS NOT NULL").fetchone()["c"]
print(f"photos with an avatar:      {withav} ({100.0*withav/tot:.1f}%)")

print("\navatars worn:")
for r in database.avatars_summary()[:8]:
    print(f"  {r['cnt']:5d}  {r['name']}   (last {r['last'][:10] if r['last'] else '?'})")

print("\nsessions with photos (newest 6):")
for r in database.sessions_with_photos(6):
    who = database.session_people(r["id"], sorted(cfg.self_names))
    print(f"  {r['start_at'][:16]}  {r['cnt']:3d} shots  {r['world_name']!r}"
          f"  with {len(who)} people")

print("\n--- year in review data ---")
years = database.years()
print("years:", years)
if years:
    y = years[0]
    print(f"  {y}: {len(database.year_photos(y))} photos, "
          f"{len(database.year_world_ids(y))} worlds, "
          f"{database.year_people_count(y, sorted(cfg.self_names))} people, "
          f"{len(database.year_active_days(y))} active days")

database.close()
print("\nOK")
