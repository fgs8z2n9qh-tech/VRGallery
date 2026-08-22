"""Check whether a newer release exists on GitHub.

One anonymous GET to the public releases endpoint; nothing about the library or
the machine is ever sent, and the whole thing can be switched off.
"""
import json
import re
import urllib.request

from . import paths

RELEASES_API = "https://api.github.com/repos/fgs8z2n9qh-tech/VRChronicle/releases/latest"
RELEASES_PAGE = "https://github.com/fgs8z2n9qh-tech/VRChronicle/releases/latest"


def _parts(version):
    nums = re.findall(r"\d+", version or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate, current):
    return _parts(candidate) > _parts(current)


def latest(timeout=8):
    """-> (tag, html_url) or (None, None). Blocking; call it off the GUI thread."""
    req = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{paths.APP_NAME}/{paths.APP_VERSION}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None, None
            data = json.loads(resp.read(1 << 20).decode("utf-8", "replace"))
    except Exception:
        return None, None
    tag = (data.get("tag_name") or "").strip()
    url = (data.get("html_url") or RELEASES_PAGE).strip()
    if not tag:
        return None, None
    return tag, url


def check(current=None):
    """-> (tag, url) when the published release is newer than this build."""
    tag, url = latest()
    if tag and is_newer(tag, current or paths.APP_VERSION):
        return tag, url
    return None, None
