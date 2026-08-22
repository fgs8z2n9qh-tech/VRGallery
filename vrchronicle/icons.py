"""Feather-style stroke icons rendered from inline SVG (crisp at any DPR)."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer

_FEATHER = {
    "image": '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>'
             '<circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 '
            '5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>'
                '<line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>'
                '<line x1="3" y1="10" x2="21" y2="10"/>',
    "layers": '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
              '<polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>'
             '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1'
             '-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>'
             '<circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/>'
             '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "user-check": '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>'
                  '<circle cx="8.5" cy="7" r="4"/><polyline points="17 11 19 13 23 9"/>',
    "award": '<circle cx="12" cy="8" r="7"/>'
             '<polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>',
    "chart": '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>'
             '<line x1="6" y1="20" x2="6" y2="14"/>',
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "settings": '<circle cx="12" cy="12" r="3"/>'
                '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1'
                '-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1'
                '-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06'
                'a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 '
                '0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 '
                '0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 '
                '0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 '
                '0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83'
                'l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 '
                '0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    # a funnel: a gear here read as "settings", which the sidebar already owns
    "filter": '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    "heart": '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0'
             '-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>'
            '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "trash": '<polyline points="3 6 5 6 21 6"/>'
             '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 '
             '1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/>'
             '<line x1="14" y1="11" x2="14" y2="17"/>',
    "send": '<line x1="22" y1="2" x2="11" y2="13"/>'
            '<polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    "play": '<polygon points="5 3 19 12 5 21 5 3"/>',
    "chevron-left": '<polyline points="15 18 9 12 15 6"/>',
    "chevron-down": '<polyline points="6 9 12 15 18 9"/>',
    "chevron-right": '<polyline points="9 18 15 12 9 6"/>',
    "arrow-left": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    "x": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 '
              '1 2 2z"/>',
    "folder-plus": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 '
                   '0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/>'
                   '<line x1="9" y1="14" x2="15" y2="14"/>',
    "external": '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
                '<polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
    "refresh": '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>'
               '<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "info": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/>'
            '<line x1="12" y1="8" x2="12.01" y2="8"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "shuffle": '<polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/>'
               '<polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/>'
               '<line x1="4" y1="4" x2="9" y2="9"/>',
    "maximize": '<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 '
                '2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>',
    "edit": '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
            '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    "aperture": '<circle cx="12" cy="12" r="10"/>'
                '<line x1="14.31" y1="8" x2="20.05" y2="17.94"/>'
                '<line x1="9.69" y1="8" x2="21.17" y2="8"/>'
                '<line x1="7.38" y1="12" x2="13.12" y2="2.06"/>'
                '<line x1="9.69" y1="16" x2="3.95" y2="6.06"/>'
                '<line x1="14.31" y1="16" x2="2.83" y2="16"/>'
                '<line x1="16.62" y1="12" x2="10.88" y2="21.94"/>',
    # the app's own mark: two fanned photo cards (the layers of a chronicle)
    "photostack": '<g transform="rotate(-15 12 12)">'
                  '<rect x="5.4" y="4.6" width="12.4" height="12.4" rx="2.4" opacity="0.55"/></g>'
                  '<g transform="rotate(7 12 12)">'
                  '<rect x="5" y="6.6" width="13.4" height="13.4" rx="2.6"/>'
                  '<circle cx="9.4" cy="11.2" r="1.5" fill="{c}" stroke="none"/></g>',
    "minimize-2": '<polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/>'
                  '<line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/>',
    "pause": '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
    "film": '<rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/>'
            '<line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/>'
            '<line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/>'
            '<line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/>'
            '<line x1="17" y1="7" x2="22" y2="7"/>',
}

_cache = {}


def _svg(name, color, width):
    body = _FEATHER[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</svg>')


def pixmap(name, color, px, dpr=1.0, width=2.0, fill=None):
    key = (name, color, px, round(dpr, 2), width, fill)
    pm = _cache.get(key)
    if pm is not None:
        return pm
    size = int(px * dpr)
    body = _FEATHER[name].replace("{c}", color)   # glyphs may need a solid accent part
    fill_attr = fill or "none"
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill_attr}" '
           f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
           f'stroke-linejoin="round">{body}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    pm.setDevicePixelRatio(dpr)
    _cache[key] = pm
    return pm


def qicon(name, color, px=20, dpr=2.0, width=2.0, fill=None):
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, px, dpr, width, fill))
    return ic


# The app mark, in the same 120-unit space the icon family generator uses, so the
# in-app logo and the shipped .ico are literally the same drawing.
APP_TILE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><defs>'
    '<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="{g0}"/><stop offset="0.55" stop-color="{g1}"/>'
    '<stop offset="1" stop-color="{g2}"/></linearGradient>'
    '<linearGradient id="gl" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#ffffff" stop-opacity="0.32"/>'
    '<stop offset="1" stop-color="#ffffff" stop-opacity="0"/></linearGradient></defs>'
    '<rect width="120" height="120" rx="30" fill="url(#g)"/>'
    '<rect x="8" y="8" width="104" height="46" rx="24" fill="url(#gl)"/>'
    '<path d="M26 22 h68 a14 14 0 0 1 14 14 v36 a14 14 0 0 1 -14 14 h-40 '
    'l-22 18 v-18 h-6 a14 14 0 0 1 -14 -14 v-36 a14 14 0 0 1 14 -14 z" fill="#ffffff"/>'
    '<circle cx="44" cy="44" r="6.5" fill="{cut}"/>'
    '<path d="M28 70 l17 -19 l12 11 l10 -9 l19 17 z" fill="{cut}"/></svg>'
)


def logo_pixmap(px, dpr=1.0, grad=None, cut=None):
    """The app tile: gradient squircle, gloss, and the chat-balloon mark."""
    from . import style
    grad = grad or style.ICON_GRAD
    svg = APP_TILE_SVG.format(g0=grad[0], g1=grad[1], g2=grad[2],
                              cut=cut or style.ICON_CUT)
    size = max(1, int(px * dpr))
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm
