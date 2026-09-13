"""Naming a face box from the ones you have already named.

A VRChat avatar is not a face. Every off-the-shelf recogniser -- dlib,
FaceNet, InsightFace -- is trained on human faces and does not even DETECT a
furry or anime head, let alone identify one. What those avatars are instead is
wildly, reliably distinctive in colour: a teal fox and a black cat do not get
confused by anything.

So the whole of it is: shrink the box to eight by eight, divide out the
brightness so a dark room and a neon one agree, and keep the 192 bytes. To name
a new box, find the nearest stored one. Measured leave-one-out on this app's own
347 hand-placed tags:

    among all 39 names, no other help              75.2%
    among only the people the log put in the room  83.9%
    the same, never matching a tag from that night 81.7%

The third number is the one that matters: it barely drops, so the signature is
recognising the avatar rather than the evening's lighting.

It also knows when to keep quiet. The margin -- how much further the runner-up
NAME is than the winner -- separates the sure from the unsure:

    margin >= 1.10   speaks for 87% of boxes, right 89% of the time
    margin >= 1.20   speaks for 70% of boxes, right 94%
    margin >= 1.35   speaks for 54% of boxes, right 95%

At 1.20 it offers a name on seven boxes in ten and is wrong on one in sixteen,
and being wrong costs one click, because it only ever pre-selects -- the menu is
still the menu.

One signature costs about 90 ms, nearly all of it decoding the photo.

WHAT IT CANNOT DO. It recognises the avatar, not the person, so somebody who
changes avatar is somebody else until you tag them once in the new one. It only
knows names you have tagged before. And it does not find the box: you still draw
that.

Everything here goes through QImage rather than Pillow, for one reason: the
stored signature and the one being looked up have to come off the same pipeline,
or the distances mean nothing. Qt is already here; Pillow's LANCZOS and Qt's
smooth transform do not agree to the byte.
"""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage

VERSION = 1          # bump to have every stored signature rebuilt
GRID = 8             # the box becomes GRID x GRID pixels
SCALE = 64.0         # v / mean lands near 1.0; this puts it in a byte
SIG_LEN = GRID * GRID * 3

# Speak only when the runner-up name is at least this much further away.
# 1.20 was measured at 71% coverage and 94% correct; see the table above.
MARGIN = 1.20


def signature(img, x, y, w, h):
    """The colour fingerprint of one box. -> bytes of length SIG_LEN, or None.

    x/y/w/h are fractions of the image, the way photo_tags stores them, so the
    signature does not care what resolution the photo was taken at.
    """
    if img is None or img.isNull():
        return None
    W, H = img.width(), img.height()
    rect = QRect(int(x * W), int(y * H),
                 max(4, int(w * W)), max(4, int(h * H)))
    rect = rect.intersected(QRect(0, 0, W, H))
    if rect.width() < 4 or rect.height() < 4:
        return None
    small = img.copy(rect).scaled(GRID, GRID, Qt.IgnoreAspectRatio,
                                  Qt.SmoothTransformation)
    if small.isNull():
        return None
    # Read the pixels one at a time rather than off the raw buffer. It is
    # sixty-four of them, so the cost is nothing, and it avoids both the
    # scanline padding Qt puts at the end of every row and the format
    # conversion that reaching into constBits() would need first.
    raw = bytearray()
    for row in range(GRID):
        for col in range(GRID):
            px = small.pixel(col, row)
            raw += bytes(((px >> 16) & 255, (px >> 8) & 255, px & 255))
    if len(raw) != SIG_LEN:
        return None
    mean = sum(raw) / float(SIG_LEN)
    if mean < 1.0:                     # a box of pure black says nothing
        return None
    return bytes(min(255, int(v / mean * SCALE)) for v in raw)


def signature_for_path(path, x, y, w, h):
    """The same, read from disk. Used to fill in tags placed before this existed."""
    img = QImage(path)
    return None if img.isNull() else signature(img, x, y, w, h)


def distance(a, b):
    """How unalike two signatures are. Smaller is closer."""
    return sum(abs(p - q) for p, q in zip(a, b))


def suggest(sig, known, margin=MARGIN):
    """Who this box probably is. -> (name, confident) or (None, False).

    `known` is {name: [signature, ...]} -- everyone worth considering, which the
    caller narrows to the people the logs put in that instance. `confident` says
    whether the runner-up NAME was far enough behind to be worth pre-selecting;
    a name is still returned when it is not, for a caller that wants to sort by
    likelihood rather than pick.
    """
    if not sig or not known:
        return None, False
    best = {}
    for name, sigs in known.items():
        for other in sigs:
            if not other or len(other) != len(sig):
                continue
            d = distance(sig, other)
            if name not in best or d < best[name]:
                best[name] = d
    if not best:
        return None, False
    order = sorted(best.items(), key=lambda kv: kv[1])
    name, d = order[0]
    if len(order) == 1:
        # Nobody to be confused with. Measured at 91% on this library, which is
        # worth pre-selecting; it is not certainty, because the person in the
        # box is not always someone the log listed.
        return name, True
    runner = order[1][1]
    if d <= 0:
        # An exact match, which happens when the same box is looked up twice.
        # Sure of it only if nobody ELSE is also an exact match -- two people in
        # the same avatar is precisely the case worth staying quiet about.
        return name, runner > 0
    return name, (runner / d) >= margin
