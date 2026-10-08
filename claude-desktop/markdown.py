# -*- coding: utf-8 -*-
"""轻量 Markdown 渲染：直接写入 tkinter Text 组件。

支持：标题、粗体、斜体、行内代码、代码块、无序/有序列表、
引用、分隔线、链接、表格（等宽对齐）。
"""

from __future__ import annotations

import re
import tkinter as tk

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)")
_CODE_RE = re.compile(r"`([^`\n]+)`")


def configure_tags(tw: tk.Text, theme) -> None:
    """注册所有 Markdown 相关 tag 的样式。主题切换时重新调用。"""
    tw.tag_configure("md_h1", font=theme.font(7, bold=True),
                     spacing1=14, spacing3=6)
    tw.tag_configure("md_h2", font=theme.font(5, bold=True),
                     spacing1=12, spacing3=5)
    tw.tag_configure("md_h3", font=theme.font(3, bold=True),
                     spacing1=10, spacing3=4)
    tw.tag_configure("md_bold", font=theme.font(0, bold=True))
    tw.tag_configure("md_italic", font=(theme.ui, theme.size, "italic"))
    tw.tag_configure("md_code", font=theme.font(mono=True),
                     background=theme.code_bg, foreground=theme.fg)
    tw.tag_configure("md_codeblock", font=theme.font(mono=True),
                     background=theme.code_bg, foreground=theme.fg,
                     lmargin1=18, lmargin2=18, rmargin=12,
                     spacing1=5, spacing3=5)
    tw.tag_configure("md_quote", lmargin1=18, lmargin2=18,
                     foreground=theme.fg_dim)
    tw.tag_configure("md_list", lmargin1=22, lmargin2=40)
    tw.tag_configure("md_hr", foreground=theme.border)
    tw.tag_configure("md_link", foreground=theme.accent, underline=True)
    tw.tag_configure("md_table", font=theme.font(mono=True), lmargin1=18,
                     lmargin2=18, spacing1=1, spacing3=1)


def _insert_inline(tw: tk.Text, text: str, theme, link_sink,
                   extra_tags: tuple[str, ...] = ()) -> None:
    """插入一行文本，处理行内标记。"""
    pos = 0
    pattern = re.compile(
        r"(?P<code>`[^`\n]+`)|(?P<bold>\*\*[^*\n]+\*\*|__[^_\n]+__)"
        r"|(?P<italic>(?<!\*)\*[^*\n]+\*(?!\*)|(?<!_)_[^_\n]+_(?!_))"
        r"|(?P<link>\[[^\]\n]+\]\([^)\s]+\))"
    )
    for match in pattern.finditer(text):
        if match.start() > pos:
            tw.insert("end", text[pos:match.start()], extra_tags)
        kind = match.lastgroup
        raw = match.group()
        if kind == "code":
            tw.insert("end", raw[1:-1], extra_tags + ("md_code",))
        elif kind == "bold":
            tw.insert("end", raw[2:-2], extra_tags + ("md_bold",))
        elif kind == "italic":
            tw.insert("end", raw[1:-1], extra_tags + ("md_italic",))
        elif kind == "link":
            lm = _LINK_RE.match(raw)
            label, url = lm.group(1), lm.group(2)
            tag = f"link_{len(link_sink)}"
            tw.insert("end", label, extra_tags + ("md_link", tag))
            link_sink.append((tag, url))
        pos = match.end()
    if pos < len(text):
        tw.insert("end", text[pos:], extra_tags)


def _flush_table(tw: tk.Text, rows: list[list[str]], theme) -> None:
    if not rows:
        return
    widths = [max(len(r[i]) if i < len(r) else 0 for r in rows)
              for i in range(max(len(r) for r in rows))]
    for idx, row in enumerate(rows):
        cells = []
        for i, width in enumerate(widths):
            cell = row[i] if i < len(row) else ""
            try:
                pad = width - sum(2 if ord(ch) > 127 else 1 for ch in cell)
            except TypeError:
                pad = 0
            cells.append(cell + " " * max(0, pad))
        tw.insert("end", "  ".join(cells).rstrip() + "\n", ("md_table",))
        if idx == 0:
            tw.insert("end", "  ".join("-" * w for w in widths) + "\n",
                      ("md_table",))


def render_markdown(tw: tk.Text, text: str, theme, link_sink: list,
                    base_tags: tuple[str, ...] = ()) -> None:
    """把 Markdown 文本渲染进 Text 组件（调用方负责先进入可写状态）。"""
    lines = text.split("\n")
    i = 0
    in_code = False
    code_lang = ""
    table_rows: list[list[str]] = []

    def flush_pending_table():
        nonlocal table_rows
        if table_rows:
            _flush_table(tw, table_rows, theme)
            table_rows = []

    while i < len(lines):
        line = lines[i]

        # 代码块围栏
        fence = re.match(r"^\s*(```|~~~)\s*(\S*)\s*$", line)
        if fence:
            if in_code:
                in_code = False
                code_lang = ""
                tw.insert("end", "\n")
            else:
                flush_pending_table()
                in_code = True
                code_lang = fence.group(2)
            i += 1
            continue

        if in_code:
            tw.insert("end", line + "\n", base_tags + ("md_codeblock",))
            i += 1
            continue

        # 表格
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells) and table_rows:
                i += 1
                continue
            table_rows.append(cells)
            i += 1
            continue
        else:
            flush_pending_table()

        stripped = line.strip()

        if not stripped:
            tw.insert("end", "\n")
            i += 1
            continue

        if re.fullmatch(r"[-*_]{3,}", stripped):
            tw.insert("end", "─" * 46 + "\n", base_tags + ("md_hr",))
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = min(len(m.group(1)), 3)
            tag = f"md_h{level}"
            _insert_inline(tw, m.group(2), theme, link_sink,
                           base_tags + (tag,))
            tw.insert("end", "\n", base_tags + (tag,))
            i += 1
            continue

        m = re.match(r"^>\s?(.*)$", stripped)
        if m:
            _insert_inline(tw, "▏ " + m.group(1), theme, link_sink,
                           base_tags + ("md_quote",))
            tw.insert("end", "\n", base_tags + ("md_quote",))
            i += 1
            continue

        m = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", stripped)
        if m:
            bullet = m.group(1)
            marker = "•  " if not bullet[0].isdigit() else bullet + " "
            indent = len(line) - len(line.lstrip())
            pad = " " * max(0, indent - 0)
            tw.insert("end", pad + marker, base_tags + ("md_list",))
            _insert_inline(tw, m.group(2), theme, link_sink,
                           base_tags + ("md_list",))
            tw.insert("end", "\n", base_tags + ("md_list",))
            i += 1
            continue

        _insert_inline(tw, line, theme, link_sink, base_tags)
        tw.insert("end", "\n", base_tags)
        i += 1

    flush_pending_table()


def plain_text_of(text: str) -> str:
    """去掉 Markdown 标记，用于生成会话标题预览。"""
    out = _CODE_RE.sub(r"\1", text)
    out = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2), out)
    out = re.sub(r"^#{1,6}\s+", "", out, flags=re.MULTILINE)
    out = out.replace("`", "")
    return out.strip()
