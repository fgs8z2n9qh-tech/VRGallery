# VRChronicle — VRChat photo album

A gallery that knows **which world** each photo was taken in and **who was there** —
because it reads the same logs VRChat throws away.

**[⬇ Download the installer](https://github.com/fgs8z2n9qh-tech/VRChronicle/releases/latest)**
· Windows 10/11, no Python needed

## Where the knowledge comes from

1. **VRCX metadata** — if VRCX runs with its screenshot helper, world + players are
   embedded in the PNG itself. Most reliable; travels with the file.
2. **VRChat logs** — `%USERPROFILE%\AppData\LocalLow\VRChat\VRChat\output_log_*.txt`
   gives a session timeline (`Joining wrld_…`, `OnPlayerJoined/Left`, and
   `Switching <you> to avatar <name>`), matched against each screenshot's timestamp.
   VRChat only keeps the last few log files, so **VRChronicle copies every session into
   its own database** — leave it running in the tray and the history never gets lost.

## What it does

- Timeline with day headers and a month/year rail, search by world / person / file,
  favorites, albums
- **Moments** — events found automatically: a run of photos taken in one sitting
  becomes "Sea Escape · Aug 8" with its people; save any of them as an album
- **Sessions** — one card per visit to a world: duration, who was there, the shots
- **Worlds / People / Avatars** — cover-art cards; a person opens a profile with when
  you first met, where you usually meet, and who else is normally around
- **Instance privacy** — every photo knows whether it was taken in a public, friends+,
  invite or group instance, and the app warns you before a private one leaves the group
- Lightbox with zoom/pan, metadata panel, clickable people & avatar chips,
  "Open on vrchat.com"
- **Memories** — "on this day, N years ago" + a random-day button
- **Statistics** — months, top worlds/people/avatars, time-of-day, storage forecast
- **Year in review** and **contact sheets** — shareable posters rendered from your library
- **Cleanup** — black shots, bursts, library-wide near-duplicates (dhash + brightness),
  huge PNGs → Recycle Bin or JPG conversion. Nothing is ever deleted permanently.
- **Backup** — verified, additive copy of the whole library to another drive
- **Headset import** — pull VRChat photos off a Quest over ADB
- **XMP sidecars** — world, people and avatar written next to the photo so Bridge,
  Lightroom and darktable can read them; the photos themselves are never modified
- **Sharing** — Discord webhook, optional burned-in caption band, captioned export
- **In-world frame** — publish one photo to your own VRChat world (see `world/`)
- **Local API** — loopback + token, so a Hexpad key can push your newest shot to
  Discord in one tap
- Tray mode + start-with-Windows, so the log watcher keeps running

## Running

```powershell
.venv\Scripts\python.exe run.py
```

Built app: `dist\VRChronicle\VRChronicle.exe` (`build.ps1`), shareable installer
`dist\VRChronicle-Setup.zip` (`make_installer.ps1`).

Flags: `--tray` (start hidden), `--index` (headless index),
`--shot out.png --page sessions` (UI screenshot for testing).

Helper scripts: `tools\selftest.py` (headless index against the real library),
`tools\integrate.py` (register the app with Atlas and Hexpad — backs their configs up
first and never overwrites an occupied slot).

## Data

Everything stays local in `%LOCALAPPDATA%\VRChronicle\` (vrchronicle.db, thumbs\,
config.json, exports\, crash.log). A library from the app's previous name is adopted
automatically on first run. Photos are only ever read — except the two Cleanup actions,
which move files to the Recycle Bin after asking.
