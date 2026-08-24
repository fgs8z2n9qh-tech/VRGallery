"""Date / size formatting (English UI)."""
from datetime import date, datetime

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

ISO = "%Y-%m-%dT%H:%M:%S"


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:19], ISO)
    except ValueError:
        return None


def day_label(day_str, today=None):
    """'2026-08-21' -> 'Friday · August 21, 2026' (Today/Yesterday prefixed)."""
    try:
        y, m, d = int(day_str[:4]), int(day_str[5:7]), int(day_str[8:10])
        dt = date(y, m, d)
    except (ValueError, TypeError):
        return day_str or "Unknown day"
    base = f"{DAYS[dt.weekday()]} · {MONTHS[m - 1]} {d}, {y}"
    today = today or date.today()
    delta = (today - dt).days
    if delta == 0:
        return "Today · " + base
    if delta == 1:
        return "Yesterday · " + base
    return base


def dt_label(iso_s):
    dt = parse_iso(iso_s)
    if not dt:
        return ""
    return (f"{DAYS[dt.weekday()]}, {MONTHS[dt.month - 1]} {dt.day}, {dt.year} · "
            f"{dt.hour:02d}:{dt.minute:02d}")


def dt_short(iso_s):
    dt = parse_iso(iso_s)
    if not dt:
        return ""
    return f"{dt.year}-{dt.month:02d}-{dt.day:02d} {dt.hour:02d}:{dt.minute:02d}"


def date_short(iso_s):
    dt = parse_iso(iso_s)
    if not dt:
        return ""
    return f"{MONTHS_SHORT[dt.month - 1]} {dt.day}, {dt.year}"


def time_label(iso_s):
    dt = parse_iso(iso_s)
    return f"{dt.hour:02d}:{dt.minute:02d}" if dt else ""


def month_label(ym):
    """'2026-08' -> \"Aug '26\"."""
    try:
        y, m = int(ym[:4]), int(ym[5:7])
        return f"{MONTHS_SHORT[m - 1]} '{y % 100:02d}"
    except (ValueError, TypeError):
        return ym


def years_ago_label(years):
    return "1 year ago" if years == 1 else f"{years} years ago"


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def count_label(n):
    return f"{n:,}"


def plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")
