"""Year in review: renders a shareable poster image from the library (Pillow only)."""
import os

from PIL import Image, ImageDraw

from . import export, fmt, imaging, paths

W = 1400
MARGIN = 48
BG = (13, 15, 21)
CARD = (22, 26, 38)
TEXT = (233, 236, 245)
DIM = (152, 162, 184)
FAINT = (101, 112, 137)


def _hex(c):
    return tuple(int(c[1 + i * 2:3 + i * 2], 16) for i in range(3))


def _rounded(im, radius):
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1],
                                           radius=radius, fill=255)
    out = Image.new("RGBA", im.size)
    out.paste(im, (0, 0), mask)
    return out


def _cover(path, size, mtime=0, filesize=0):
    """Load a photo cropped to fill `size`, preferring the on-disk thumbnail cache."""
    src = None
    try:
        key = imaging.thumb_key(path, mtime or 0, filesize or 0)
        tp = imaging.thumb_path(key)
        if os.path.exists(tp) and max(size) <= imaging.THUMB_PX:
            src = Image.open(tp).convert("RGB")
    except Exception:
        src = None
    if src is None:
        try:
            src = export.load_oriented(path)
        except Exception:
            return Image.new("RGB", size, CARD)
    sw, sh = src.size
    scale = max(size[0] / sw, size[1] / sh)
    src = src.resize((max(1, int(sw * scale)), max(1, int(sh * scale))), Image.LANCZOS)
    x = (src.size[0] - size[0]) // 2
    y = (src.size[1] - size[1]) // 2
    return src.crop((x, y, x + size[0], y + size[1]))


def _bar(d, x, y, w, h, frac, a, b, track=(28, 33, 48)):
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=track)
    bw = max(h, int(w * max(0.0, min(1.0, frac))))
    for i in range(bw):
        t = i / max(1, bw - 1)
        c = tuple(int(a[j] * (1 - t) + b[j] * t) for j in range(3))
        d.line([(x + i, y), (x + i, y + h)], fill=c)


def _list_block(d, x, y, w, title, rows, accent_a, accent_b):
    d.text((x, y), title.upper(), font=export._font(15, True), fill=FAINT)
    y += 34
    if not rows:
        d.text((x, y), "no data", font=export._font(17), fill=FAINT)
        return y + 30
    top = max(r[1] for r in rows) or 1
    for name, cnt in rows:
        f = export._font(19)
        label = name or "?"
        while d.textlength(label, font=f) > w * 0.52 and len(label) > 4:
            label = label[:-2]
            if d.textlength(label + "…", font=f) <= w * 0.52:
                label += "…"
        d.text((x, y), label, font=f, fill=TEXT)
        bar_x = x + int(w * 0.56)
        bar_w = int(w * 0.32)
        _bar(d, bar_x, y + 8, bar_w, 10, cnt / top, accent_a, accent_b)
        num = fmt.count_label(cnt)
        fn = export._font(17)
        d.text((x + w - d.textlength(num, font=fn), y + 1), num, font=fn, fill=DIM)
        y += 40
    return y


def _pick_variety(rows, want=9, max_per_world=3, hash_distance=14):
    """Thin a ranked pool so the grid is not nine shots of the same moment."""
    picked, picked_ids, seen_days, per_world, hashes = [], set(), set(), {}, []
    for pool_pass in (0, 1):          # first pass one-per-day, then relax
        for r in rows:
            if len(picked) >= want:
                break
            if r["id"] in picked_ids:
                continue
            if pool_pass == 0 and r["day"] in seen_days:
                continue
            # photos with no world must not all share one bucket, or the whole
            # unknown-world half of the library would be capped at max_per_world
            wid = r["world_id"] or f"?{r['id']}"
            if per_world.get(wid, 0) >= max_per_world:
                continue
            h = r["dhash"]
            if h:
                try:
                    hv = int(h, 16)
                except (TypeError, ValueError):
                    hv = None
                if hv is not None:
                    if any((hv ^ o).bit_count() <= hash_distance for o in hashes):
                        continue
                    hashes.append(hv)
            picked.append(r)
            picked_ids.add(r["id"])
            seen_days.add(r["day"])
            per_world[wid] = per_world.get(wid, 0) + 1
        if len(picked) >= want:
            break
    return picked


def build(db, year, self_names, accent=("#34d97a", "#8ae05e"), out_path=None):
    """Render the poster; returns (path, stats_dict) or (None, None) when the year is empty."""
    a, b = _hex(accent[0]), _hex(accent[1])

    rows = db.year_photos(year)
    if not rows:
        return None, None
    total = len(rows)
    size_sum = sum(r["filesize"] or 0 for r in rows)
    worlds = db.year_top_worlds(year, 6)
    people = db.year_top_people(year, 6, self_names)
    avatars = db.year_top_avatars(year, 3)
    days = db.year_active_days(year)
    picks = _pick_variety(db.year_best_candidates(year), 9)

    cols, gap = 3, 14
    cell_w = (W - MARGIN * 2 - gap * (cols - 1)) // cols
    cell_h = int(cell_w * 9 / 16)
    grid_rows = (len(picks) + cols - 1) // cols if picks else 0
    grid_h = grid_rows * cell_h + max(0, grid_rows - 1) * gap

    head_h = 250
    stat_h = 150
    lists_h = 40 + max(len(worlds), len(people)) * 40 + 30
    foot_h = 96
    H = head_h + stat_h + (grid_h + 46 if grid_h else 0) + lists_h + foot_h

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    # ---- header ----
    d.text((MARGIN, 56), str(year), font=export._font(112, True), fill=TEXT)
    yw = d.textlength(str(year), font=export._font(112, True))
    d.text((MARGIN + yw + 22, 108), "in VRChat", font=export._font(46, True), fill=DIM)
    for i in range(W - MARGIN * 2):
        t = i / max(1, W - MARGIN * 2 - 1)
        c = tuple(int(a[j] * (1 - t) + b[j] * t) for j in range(3))
        d.line([(MARGIN + i, 196), (MARGIN + i, 200)], fill=c)
    sub = f"{fmt.count_label(total)} photos · {len(days)} days with a camera out"
    d.text((MARGIN, 214), sub, font=export._font(22), fill=DIM)

    # ---- stat tiles ----
    y = head_h
    tiles = [(fmt.count_label(total), "photos"),
             (fmt.count_label(len(db.year_world_ids(year))), "worlds"),
             (fmt.count_label(db.year_people_count(year, self_names)), "people"),
             (fmt.human_size(size_sum), "captured")]
    tw = (W - MARGIN * 2 - gap * 3) // 4
    for i, (num, lab) in enumerate(tiles):
        x = MARGIN + i * (tw + gap)
        d.rounded_rectangle([x, y, x + tw, y + 112], radius=16, fill=CARD)
        d.text((x + 22, y + 22), num, font=export._font(38, True), fill=TEXT)
        d.text((x + 22, y + 72), lab, font=export._font(18), fill=DIM)
    y += stat_h

    # ---- best-of grid ----
    if picks:
        for i, r in enumerate(picks):
            cx = MARGIN + (i % cols) * (cell_w + gap)
            cy = y + (i // cols) * (cell_h + gap)
            img = _cover(r["path"], (cell_w, cell_h), r["mtime"], r["filesize"])
            canvas.paste(_rounded(img, 14), (cx, cy), _rounded(img, 14))
        y += grid_h + 46

    # ---- top lists ----
    col_w = (W - MARGIN * 2 - 60) // 2
    _list_block(d, MARGIN, y, col_w, "Top worlds",
                [(w["name"], w["c"]) for w in worlds], a, b)
    _list_block(d, MARGIN + col_w + 60, y, col_w, "Most seen",
                [(p["name"], p["c"]) for p in people], a, b)
    y += lists_h

    # ---- footer ----
    foot = paths.APP_NAME
    d.text((MARGIN, y + 20), foot, font=export._font(20, True), fill=FAINT)
    if avatars:
        worn = ", ".join(av["name"] for av in avatars if av["name"])
        if worn:
            t = f"worn this year: {worn}"
            f = export._font(18)
            while d.textlength(t, font=f) > W - MARGIN * 2 - 160 and len(t) > 20:
                t = t[:-2] + "…"
            d.text((W - MARGIN - d.textlength(t, font=f), y + 21), t, font=f, fill=FAINT)

    out_path = out_path or os.path.join(export.ensure_export_dir(),
                                        f"{paths.APP_NAME} {year}.jpg")
    canvas.save(out_path, "JPEG", quality=93, optimize=True)
    return out_path, {"total": total, "days": len(days), "bytes": size_sum}
