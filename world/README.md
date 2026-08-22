# In-world photo frame

Two halves:

1. **VRChronicle side** — Settings ▸ *In-world frame*: pick a **frame folder** and
   (optionally) a **publish command**. Then right-click any photo ▸ *Send to world frame*.
   The app writes `frame.jpg` + `frame.json` into that folder and runs your command.
   **VRChronicle never uploads anything by itself** — the folder and the command are yours.

2. **Unity side** — `VRChroniclePhotoFrame.cs` (UdonSharp) downloads that published
   image and shows it on a quad, refreshing on an interval.

## Getting a public https URL

The Udon `VRCImageDownloader` needs a plain https URL that returns an image. Options:

| Host | Frame folder | Publish command |
|---|---|---|
| GitHub Pages | your repo working copy | `git add -A && git commit -m "frame" && git push` |
| Any static web host | the synced/web root | *(empty — the sync tool handles it)* |
| Cloudflare R2 / S3 | a staging folder | your CLI's `cp`/`sync` command |

Then paste the resulting URL (e.g. `https://<user>.github.io/<repo>/frame.jpg`)
into the `imageUrl` field on the prefab.

⚠️ Whatever you publish becomes **publicly readable** by anyone with the URL, and
anyone in the world can see it. Only publish photos you are happy to make public.

## Unity setup (this project: Unity 2022.3.22f1, Worlds SDK 3.10.4, Built-in RP)

1. Copy `VRChroniclePhotoFrame.cs` into `Assets\_Project\PhotoFrame\`.
2. Create a Quad, scale `2.88 × 1.62 × 1` (16:9 — same as the world's ProTV screen).
3. Material: **Unlit/Texture** (Built-in RP — the project has URP installed but *not* active).
4. Add the `VRChroniclePhotoFrame` component; assign `targetRenderer` (the quad) and
   optionally `fallbackTexture`.
5. Paste your URL into `imageUrl`, set `refreshSeconds` (300 is a good default; 0 = once).

### Two things that trip people up

- The `VRCImageDownloader` **must** stay in a field (it does here). As a local variable
  it gets collected and the image silently never appears.
- Visitors need *Allow Untrusted URLs* on unless the host is VRChat-trusted, so always
  assign a `fallbackTexture` or the frame just looks broken to them.

### Caching note

VRChat caches downloaded images per URL for the session. If you republish to the same
filename, players who already loaded it may keep the old one until they rejoin — that is
why `refreshSeconds` exists, and why a cache-busting query string does **not** help
(the URL must stay static for the whitelist check).
