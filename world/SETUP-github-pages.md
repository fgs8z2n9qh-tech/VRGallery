# Hosting the frame image on GitHub Pages

The Udon frame needs a plain `https://` URL that returns an image. If the app already
lives in a GitHub repo, that repo can host it for free — no extra service, no account.

**Publishing puts the photo on the public internet.** Anyone with the URL can see it,
and so can everyone who visits your world. VR Gallery warns you if the photo came from
a friends-only or invite instance, but the decision is yours every time.

## One-time setup

1. Create an orphan branch that holds only the frame:

   ```bash
   git switch --orphan gh-pages
   git rm -rf .
   mkdir frame
   printf 'VRGallery frame\n' > frame/README.txt
   git add -A && git commit -m "frame host" && git push -u origin gh-pages
   git switch main
   ```

2. Repo ▸ Settings ▸ Pages ▸ Source: **Deploy from a branch**, branch `gh-pages`, `/`.

3. Clone that branch somewhere as a working copy — this is what the app writes into:

   ```bash
   git clone --branch gh-pages <your repo url> C:\vrgallery-frame
   ```

4. In VR Gallery ▸ Settings ▸ **In-world frame**:
   - **Frame folder**: `C:\vrgallery-frame\frame`
   - **Publish command**:
     ```
     git add -A && git commit -m "frame" && git push
     ```

5. Your URL is then `https://<user>.github.io/<repo>/frame/frame.jpg`. Paste it into the
   prefab's `imageUrl` field (see [README.md](README.md)).

## Using it

Right-click any photo ▸ **Send to world frame**. The app writes `frame.jpg`, runs your
command, and a minute later the wall in your world has the new picture.

## Notes

- GitHub Pages caches aggressively; `refreshSeconds` on the prefab is what eventually
  picks up a change. Do not add a cache-busting query string — the URL has to stay
  constant for VRChat's allowlist check.
- Every published frame stays in the branch's git history. To publish without keeping a
  trail, amend instead: `git add -A && git commit --amend -m frame && git push --force`.
- Pages is for small, public files. Do not point the frame folder at a repo that holds
  anything you would not put on a billboard.
