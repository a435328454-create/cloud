# -*- coding: utf-8 -*-
"""配色与字体。"""

from __future__ import annotations

import tkinter.font as tkfont

FONT_CANDIDATES = ["Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑",
                   "PingFang SC", "Noto Sans CJK SC", "SimHei"]
MONO_CANDIDATES = ["Cascadia Mono", "Consolas", "Courier New", "SimSun"]


def pick_font(root, candidates: list[str], fallback: str) -> str:
    available = set(tkfont.families(root))
    for name in candidates:
        if name in available:
            return name
    return fallback


class Theme:
    def __init__(self, root, size: int = 11):
        self.ui = pick_font(root, FONT_CANDIDATES, "TkDefaultFont")
        self.mono = pick_font(root, MONO_CANDIDATES, "Courier New")
        self.size = size
        self.mono_size = size
        self.small = max(8, size - 1)

        self.bg = "#ffffff"
        self.bg_side = "#f4f5f7"
        self.bg_input = "#ffffff"
        self.fg = "#1f2328"
        self.fg_dim = "#6b7280"
        self.border = "#e3e5e8"
        self.accent = "#c96442"
        self.accent_fg = "#ffffff"
        self.bubble_user = "#f0eee9"
        self.bubble_tool = "#fafaf9"
        self.code_bg = "#f5f5f4"
        self.error = "#b42318"
        self.thinking_fg = "#8b8f96"

    def font(self, delta: int = 0, bold: bool = False, mono: bool = False):
        fam = self.mono if mono else self.ui
        size = (self.mono_size if mono else self.size) + delta
        return (fam, size, "bold") if bold else (fam, size)


DARK = {
    "bg": "#1e1f22", "bg_side": "#191a1c", "bg_input": "#26282c",
    "fg": "#e6e6e6", "fg_dim": "#9aa0a6", "border": "#34363b",
    "accent": "#d97856", "accent_fg": "#ffffff", "bubble_user": "#2d3035",
    "bubble_tool": "#24262a", "code_bg": "#26282c", "error": "#ff8a80",
    "thinking_fg": "#8b8f96",
}

LIGHT = {
    "bg": "#ffffff", "bg_side": "#f4f5f7", "bg_input": "#ffffff",
    "fg": "#1f2328", "fg_dim": "#6b7280", "border": "#e3e5e8",
    "accent": "#c96442", "accent_fg": "#ffffff", "bubble_user": "#f0eee9",
    "bubble_tool": "#fafaf9", "code_bg": "#f5f5f4", "error": "#b42318",
    "thinking_fg": "#8b8f96",
}


def apply_palette(theme: Theme, dark: bool) -> None:
    for key, value in (DARK if dark else LIGHT).items():
        setattr(theme, key, value)
