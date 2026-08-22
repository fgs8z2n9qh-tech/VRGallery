"""Palette + stylesheet. One dark theme, four accent presets."""
import os

PAL = {
    "bg":       "#0d0f15",
    "sidebar":  "#101320",
    "surface":  "#161a26",
    "surface2": "#1c2130",
    "hover":    "#232939",
    "border":   "#262c3d",
    "border2":  "#303748",
    "text":     "#e9ecf5",
    "dim":      "#98a2b8",
    "faint":    "#657089",
    "star":     "#ffd166",
    "danger":   "#ff6b6b",
    "ok":       "#3be0a0",
}

ACCENTS = {
    "vrblue": {"a": "#3d8bff", "b": "#5ad4ff", "label": "VR Blue"},
    "green":  {"a": "#34d97a", "b": "#8ae05e", "label": "Green"},
    "mint":   {"a": "#3be0a0", "b": "#2ac0e0", "label": "Mint"},
    "orchid": {"a": "#c064ff", "b": "#ff6b9e", "label": "Orchid"},
    "amber":  {"a": "#ffb04a", "b": "#ff7a59", "label": "Amber"},
}
DEFAULT_ACCENT = "vrblue"

ICON_GRAD = ("#5ac8ff", "#2d7df6", "#1b3fa8")   # app icon (family style), accent-independent
ICON_CUT = "#2f6fd8"                            # stands in for a punched-out hole


def accent(cfg_accent):
    return ACCENTS.get(cfg_accent, ACCENTS[DEFAULT_ACCENT])


# the accent currently applied, for the few things painted by hand rather than
# by the stylesheet
ACTIVE = ACCENTS[DEFAULT_ACCENT]


def mix(hex_color, alpha):
    """#rrggbb -> rgba() string."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _arrow_url():
    """A 12px chevron png on disk for the QComboBox arrow (QSS can't inline SVG)."""
    from . import icons, paths
    p = os.path.join(paths.APPDIR, "ui_arrow.png")
    try:
        if not os.path.exists(p):
            icons.pixmap("chevron-down", PAL["dim"], 12, 1.0).save(p, "PNG")
    except Exception:
        return ""
    return p.replace("\\", "/")


def build_qss(accent_key=DEFAULT_ACCENT):
    global ACTIVE
    ac = ACTIVE = accent(accent_key)
    A, B = ac["a"], ac["b"]
    P = PAL
    arrow = _arrow_url()
    return f"""
* {{ outline: none; }}
QWidget {{
    background: transparent;
    color: {P['text']};
    font-family: 'Segoe UI Variable Text', 'Segoe UI';
    font-size: 13px;
}}
QMainWindow, #Root {{ background: {P['bg']}; }}
#Sidebar {{ background: {P['sidebar']}; border-right: 1px solid {P['border']}; }}
#PageHeaderTitle {{ font-size: 21px; font-weight: 600; }}
#PageHeaderSub {{ color: {P['dim']}; font-size: 12px; }}
#SectionLabel {{
    color: {P['faint']}; font-size: 10px; font-weight: 600;
    letter-spacing: 1.2px; text-transform: uppercase;
}}
#BrandName {{ font-size: 17px; font-weight: 700; letter-spacing: 0.2px; }}
#SidebarStatus {{ color: {P['faint']}; font-size: 11px; }}

/* --- nav --- */
QPushButton#NavBtn {{
    text-align: left; padding: 9px 12px; border: none; border-radius: 10px;
    color: {P['dim']}; font-size: 13px; font-weight: 500;
}}
QPushButton#NavBtn:hover {{ background: {P['hover']}; color: {P['text']}; }}
QPushButton#NavBtn:checked {{
    background: {P['surface2']}; color: {P['text']}; font-weight: 600;
}}

/* --- buttons --- */
QPushButton#PrimaryBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {A}, stop:1 {B});
    color: #ffffff; border: none; border-radius: 10px;
    padding: 8px 18px; font-weight: 600;
}}
QPushButton#PrimaryBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {mix(A, 0.85)}, stop:1 {mix(B, 0.85)});
}}
QPushButton#PrimaryBtn:disabled {{ background: {P['surface2']}; color: {P['faint']}; }}
QPushButton#GhostBtn {{
    background: {P['surface']}; border: 1px solid {P['border']};
    border-radius: 10px; padding: 8px 14px; color: {P['text']};
}}
QPushButton#GhostBtn:hover {{ background: {P['hover']}; border-color: {P['border2']}; }}
QPushButton#DangerBtn {{
    background: rgba(255,107,107,0.12); border: 1px solid rgba(255,107,107,0.35);
    border-radius: 10px; padding: 8px 14px; color: {P['danger']}; font-weight: 600;
}}
QPushButton#DangerBtn:hover {{ background: rgba(255,107,107,0.2); }}
QPushButton#IconBtn {{
    background: transparent; border: none; border-radius: 9px; padding: 6px;
}}
QPushButton#IconBtn:hover {{ background: {P['hover']}; }}
QPushButton#IconBtn:checked {{ background: {mix(A, 0.18)}; }}
QPushButton#PillBtn {{
    background: {P['surface2']}; border: 1px solid {P['border']};
    border-radius: 14px; padding: 5px 12px; color: {P['dim']};
    /* the same weight checked and unchecked: a bolder label needs more room
       than the button was measured for, and the text ends up clipped */
    font-size: 12px; font-weight: 600;
}}
QPushButton#PillBtn:hover {{ background: {P['hover']}; color: {P['text']}; }}
/* there was no :checked rule at all, so a segmented control never showed
   which segment you were on */
QPushButton#PillBtn:checked {{
    background: {A}; border-color: {A}; color: #0b0e14;
}}
QPushButton#PillBtn:checked:hover {{ background: {mix(A, 0.85)}; color: #0b0e14; }}
QPushButton#LinkBtn {{
    background: transparent; border: none; color: {A}; font-weight: 600; padding: 4px;
}}
QPushButton#LinkBtn:hover {{ color: {B}; }}

/* --- inputs --- */
QLineEdit {{
    background: {P['surface']}; border: 1px solid {P['border']};
    border-radius: 10px; padding: 7px 12px; color: {P['text']};
    selection-background-color: {mix(A, 0.45)};
}}
QLineEdit:focus {{ border-color: {A}; }}
QLineEdit#SearchBox {{ border-radius: 16px; padding: 7px 12px 7px 32px; }}
QSpinBox {{
    background: {P['surface']}; border: 1px solid {P['border']};
    border-radius: 8px; padding: 5px 8px;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; background: transparent; }}
QSpinBox:focus {{ border-color: {A}; }}
QComboBox {{
    background: {P['surface']}; border: 1px solid {P['border']};
    border-radius: 10px; padding: 6px 26px 6px 12px; color: {P['text']};
}}
QComboBox:hover {{ background: {P['hover']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; margin-right: 6px; }}
QComboBox QAbstractItemView {{
    background: {P['surface2']}; border: 1px solid {P['border2']};
    border-radius: 10px; padding: 4px; color: {P['text']};
    selection-background-color: {P['hover']};
}}
QCheckBox {{ spacing: 8px; color: {P['text']}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 5px;
    border: 1px solid {P['border2']}; background: {P['surface']};
}}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {A}, stop:1 {B});
    border-color: transparent;
}}

/* --- slider --- */
QSlider::groove:horizontal {{
    height: 4px; background: {P['surface2']}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {A}, stop:1 {B});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
    background: #ffffff; border: none;
}}

/* --- scrollbars --- */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {P['border2']}; border-radius: 4px; min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: {P['faint']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {P['border2']}; border-radius: 4px; min-width: 40px;
}}
QScrollBar::handle:horizontal:hover {{ background: {P['faint']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* --- menus / tooltips --- */
QMenu {{
    background: {P['surface2']}; border: 1px solid {P['border2']};
    border-radius: 12px; padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 12px; border-radius: 8px; color: {P['text']};
}}
QMenu::item:selected {{ background: {P['hover']}; }}
QMenu::item:disabled {{ color: {P['faint']}; }}
QMenu::separator {{ height: 1px; background: {P['border']}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 10px; }}
QToolTip {{
    background: {P['surface2']}; color: {P['text']};
    border: 1px solid {P['border2']}; border-radius: 6px; padding: 5px 8px;
}}

/* --- cards / views --- */
#Card {{
    background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 14px;
}}
#CardTitle {{ font-size: 13px; font-weight: 600; color: {P['dim']}; }}
QListView {{
    background: transparent; border: none;
}}
QScrollArea {{ border: none; background: transparent; }}
#GridStatus {{ color: {P['faint']}; font-size: 11px; }}

/* --- lightbox --- */
#LightboxPanel {{
    background: {P['sidebar']}; border-left: 1px solid {P['border']};
}}
#LbTitle {{ font-size: 14px; font-weight: 600; }}
#LbDim {{ color: {P['dim']}; font-size: 12px; }}
#LbKey {{ color: {P['faint']}; font-size: 11px; }}
QPushButton#Chip {{
    background: {P['surface2']}; border: 1px solid {P['border']};
    border-radius: 13px; padding: 4px 11px; color: {P['text']}; font-size: 12px;
}}
QPushButton#Chip:hover {{ border-color: {A}; color: {A}; }}
QPushButton#ChipSelf {{
    background: {mix(A, 0.14)}; border: 1px solid {mix(A, 0.4)};
    border-radius: 13px; padding: 4px 11px; color: {A}; font-size: 12px;
}}

/* --- selection bar / toast --- */
#SelBar {{
    background: {P['surface2']}; border: 1px solid {P['border2']}; border-radius: 16px;
}}
#SelCount {{ font-weight: 600; padding: 0 6px; }}
#Toast {{
    background: {P['surface2']}; border: 1px solid {P['border2']}; border-radius: 12px;
}}
#ToastText {{ color: {P['text']}; font-size: 12px; }}

QProgressBar {{
    background: {P['surface2']}; border: none; border-radius: 3px; height: 6px; text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {A}, stop:1 {B});
    border-radius: 3px;
}}
"""
