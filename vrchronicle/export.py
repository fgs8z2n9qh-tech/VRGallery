"""Export helpers: downscaled copies and captioned photo cards (Pillow only)."""
import os
import re
import shutil
import time

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import fmt, paths

FONT_DIR = "C:/Windows/Fonts/"


def _font(px, bold=False):
    names = (("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf") if bold
             else ("segoeui.ttf", "arial.ttf"))
    from PIL import ImageFont
    for n in names:
        try:
            return ImageFont.truetype(FONT_DIR + n, px)
        except OSError:
            continue
    from PIL import ImageFont as _IF
    return _IF.load_default()


def _safe_name(s, fallback="photo"):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (s or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:60] or fallback


def ensure_export_dir():
    os.makedirs(paths.EXPORT_DIR, exist_ok=True)
    return paths.EXPORT_DIR


def load_oriented(path):
    with Image.open(path) as im:
        im.load()
        return ImageOps.exif_transpose(im).convert("RGB")


def downscaled_copy(path, out_path, max_px=2560, quality=90):
    """A smaller JPEG of the photo — for clipboard/share without moving 10 MB around."""
    im = load_oriented(path)
    im.thumbnail((max_px, max_px), Image.LANCZOS)
    im.save(out_path, "JPEG", quality=quality, optimize=True)
    return out_path


def _fit_text(draw, text, font_factory, start_px, max_w, min_px=12):
    """Shrink until it fits; returns (font, text) with an ellipsis fallback."""
    px = start_px
    while px > min_px:
        f = font_factory(px)
        if draw.textlength(text, font=f) <= max_w:
            return f, text
        px -= 2
    f = font_factory(min_px)
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return f, (text + "…" if text else "")


def captioned_card(photo_path, world, taken_at, people, out_path,
                   max_px=2560, quality=92, accent=("#34d97a", "#8ae05e")):
    """The photo with a caption band burned in: world, date, who was there."""
    im = load_oriented(photo_path)
    im.thumbnail((max_px, max_px), Image.LANCZOS)
    w, h = im.size

    band = max(96, int(h * 0.135))
    pad = int(band * 0.30)
    canvas = Image.new("RGB", (w, h + band), (13, 15, 21))
    canvas.paste(im, (0, 0))

    # a blurred, darkened strip of the photo's bottom edge makes the band feel attached
    strip = im.crop((0, max(0, h - band), w, h)).filter(ImageFilter.GaussianBlur(18))
    strip = Image.blend(strip, Image.new("RGB", strip.size, (13, 15, 21)), 0.82)
    canvas.paste(strip.resize((w, band)), (0, h))

    d = ImageDraw.Draw(canvas)
    # accent hairline between photo and band
    for i, x in enumerate(range(0, w)):
        t = x / max(1, w - 1)
        c = tuple(int(int(accent[0][1 + j * 2:3 + j * 2], 16) * (1 - t) +
                      int(accent[1][1 + j * 2:3 + j * 2], 16) * t) for j in range(3))
        d.line([(x, h), (x, h + 3)], fill=c)

    mark = paths.APP_NAME
    f_mark = _font(max(11, int(band * 0.15)), True)
    mark_w = d.textlength(mark, font=f_mark)
    text_w = int(w - pad * 2 - mark_w - pad)      # keep clear of the wordmark

    title = world or "Unknown world"
    f_title, title = _fit_text(d, title, lambda p: _font(p, True),
                               int(band * 0.34), text_w)
    d.text((pad, h + pad), title, font=f_title, fill=(240, 243, 250))

    sub = fmt.dt_label(taken_at) or ""
    others = [p for p in (people or [])]
    if others:
        shown = ", ".join(others[:3])
        if len(others) > 3:
            shown += f" +{len(others) - 3}"
        sub = f"{sub}   ·   with {shown}" if sub else f"with {shown}"
    f_sub, sub = _fit_text(d, sub, lambda p: _font(p, False),
                           int(band * 0.21), text_w)
    d.text((pad, h + pad + int(band * 0.40)), sub, font=f_sub, fill=(152, 162, 184))
    d.text((w - pad - mark_w, h + band - pad * 0.75 - int(band * 0.15)), mark,
           font=f_mark, fill=(101, 112, 137))

    canvas.save(out_path, "JPEG", quality=quality, optimize=True)
    return out_path


def suggest_name(world, taken_at, suffix="card"):
    stamp = (taken_at or "").replace(":", "-").replace("T", "_")[:19] or "photo"
    return f"{_safe_name(world, 'VRChat')} {stamp} {suffix}.jpg"


# ---------------------------------------------------------------- XMP sidecars

def _xml_escape(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def xmp_sidecar(photo_path, world, taken_at, people, avatar="", instance_type="",
                on_existing="backup"):
    """Write photo.xmp next to the original so Bridge/Lightroom/darktable can read
    the world and the company. The photo file itself is never touched.

    A sidecar written by another program holds real work — crops, exposure, star
    ratings — so it is copied aside first (on_existing='backup') or left alone
    ('skip'). Our own sidecars are recognised by the xmptk marker and refreshed
    in place, so repeat runs do not pile up backups.
    """
    keywords = list(people or [])
    if world:
        keywords.append(world)
    if avatar:
        keywords.append(avatar)
    bag = "".join(f"<rdf:li>{_xml_escape(k)}</rdf:li>" for k in keywords)
    desc_bits = [b for b in (world, fmt.dt_label(taken_at)) if b]
    if people:
        desc_bits.append("with " + ", ".join(people))
    if instance_type:
        desc_bits.append(f"{instance_type} instance")
    desc = _xml_escape(" · ".join(desc_bits))
    when = _xml_escape((taken_at or "")[:19])

    xml = f"""<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="{paths.APP_NAME} {paths.APP_VERSION}">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">
   <xmp:CreateDate>{when}</xmp:CreateDate>
   <photoshop:Headline>{_xml_escape(world)}</photoshop:Headline>
   <dc:description><rdf:Alt><rdf:li xml:lang="x-default">{desc}</rdf:li></rdf:Alt></dc:description>
   <dc:subject><rdf:Bag>{bag}</rdf:Bag></dc:subject>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""
    out = os.path.splitext(photo_path)[0] + ".xmp"
    if os.path.exists(out):
        try:
            with open(out, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(2048)
        except OSError:
            head = ""
        if f'x:xmptk="{paths.APP_NAME}' not in head:      # somebody else's work
            if on_existing == "skip":
                return None
            shutil.copy2(out, f"{out}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(xml)
    os.replace(tmp, out)
    return out


# ---------------------------------------------------------------- contact sheet

def contact_sheet(entries, title, subtitle, out_path, cols=4, cell_w=460,
                  accent=("#34d97a", "#8ae05e"), thumb_loader=None):
    """A poster of one session/day: `entries` are (path, mtime, filesize) tuples."""
    from PIL import ImageDraw

    gap, margin = 12, 40
    cell_h = int(cell_w * 9 / 16)
    rows = (len(entries) + cols - 1) // cols
    width = margin * 2 + cols * cell_w + (cols - 1) * gap
    head_h = 150
    height = head_h + rows * cell_h + max(0, rows - 1) * gap + margin + 46

    canvas = Image.new("RGB", (width, height), (13, 15, 21))
    d = ImageDraw.Draw(canvas)

    f_title = _font(40, True)
    t = title or ""
    while d.textlength(t, font=f_title) > width - margin * 2 and len(t) > 8:
        t = t[:-2]
    d.text((margin, 44), t, font=f_title, fill=(233, 236, 245))
    d.text((margin, 96), subtitle or "", font=_font(20), fill=(152, 162, 184))
    a = tuple(int(accent[0][1 + i * 2:3 + i * 2], 16) for i in range(3))
    b = tuple(int(accent[1][1 + i * 2:3 + i * 2], 16) for i in range(3))
    for i in range(width - margin * 2):
        t2 = i / max(1, width - margin * 2 - 1)
        d.line([(margin + i, 132), (margin + i, 135)],
               fill=tuple(int(a[j] * (1 - t2) + b[j] * t2) for j in range(3)))

    for i, ent in enumerate(entries):
        x = margin + (i % cols) * (cell_w + gap)
        y = head_h + (i // cols) * (cell_h + gap)
        try:
            im = thumb_loader(ent, (cell_w, cell_h)) if thumb_loader else None
            if im is None:
                im = load_oriented(ent[0])
                sw, sh = im.size
                sc = max(cell_w / sw, cell_h / sh)
                im = im.resize((max(1, int(sw * sc)), max(1, int(sh * sc))), Image.LANCZOS)
                ox = (im.size[0] - cell_w) // 2
                oy = (im.size[1] - cell_h) // 2
                im = im.crop((ox, oy, ox + cell_w, oy + cell_h))
        except Exception:
            im = Image.new("RGB", (cell_w, cell_h), (28, 33, 48))
        mask = Image.new("L", (cell_w, cell_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, cell_w - 1, cell_h - 1],
                                               radius=12, fill=255)
        canvas.paste(im, (x, y), mask)

    d.text((margin, height - margin), paths.APP_NAME, font=_font(18, True),
           fill=(101, 112, 137))
    canvas.save(out_path, "JPEG", quality=92, optimize=True)
    return out_path
