# -*- coding: utf-8 -*-
"""Claude 桌面版（中文界面）。

Python + Tkinter 实现，通过 stream-json 协议驱动 claude CLI。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import engine as eng
import markdown as md
import store
import theme as th

APP_TITLE = "Claude 桌面版"
MAX_TOOL_LINES = 8


class ClaudeDesktopApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = store.load_config()
        self.theme = th.Theme(root, size=int(self.cfg.get("font_size", 11)))
        th.apply_palette(self.theme, bool(self.cfg.get("dark", False)))

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.engine = eng.ClaudeEngine(
            lambda kind, payload: self.events.put((kind, payload)))

        # 会话状态
        self.session_id = store.new_session_id()
        self.cli_session_id: str | None = None
        self.session_title = "新会话"
        self.messages: list[dict] = []
        self.busy = False
        self.link_sink: list[tuple[str, str]] = []
        self.pending_assistant_msg: dict | None = None
        self._reset_stream()

        self.root.geometry("1180x780")
        self.root.minsize(900, 560)
        self._build_ui()
        self._refresh_sessions()
        self._welcome()
        self.root.after(60, self._pump)

    def _reset_stream(self) -> None:
        self.header_open = False
        self.think_open = False
        self.block_start: str | None = None
        self.partial_start: str | None = None
        self.stream_buf = ""

    @property
    def stream_in_code(self) -> bool:
        """当前流式内容是否处在未闭合的代码围栏内（用于尾行高亮）。"""
        fences = sum(1 for ln in self.stream_buf.split("\n")
                     if ln.lstrip().startswith("```")
                     or ln.lstrip().startswith("~~~"))
        return fences % 2 == 1

    # ================= 界面构建 =================

    def _build_ui(self) -> None:
        t = self.theme
        self.root.title(APP_TITLE)
        self.root.configure(bg=t.bg)

        self._init_ttk_style()
        self._build_sidebar()

        main = tk.Frame(self.root, bg=t.bg)
        main.pack(side="left", fill="both", expand=True)

        self._build_header(main)

        body = tk.Frame(main, bg=t.bg)
        body.pack(fill="both", expand=True)

        self._build_chat(body)
        self._build_input(main)

        self.root.bind("<Control-Return>", lambda _e: self._on_send())
        self.root.bind("<Escape>", lambda _e: self._on_stop())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_ttk_style(self) -> None:
        t = self.theme
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("CN.Vertical.TScrollbar", background=t.bg_side,
                        troughcolor=t.bg, bordercolor=t.bg, arrowcolor=t.fg_dim,
                        relief="flat", width=10)
        style.map("CN.Vertical.TScrollbar",
                  background=[("active", t.border)])

    # ---------- 侧边栏 ----------

    def _build_sidebar(self) -> None:
        t = self.theme
        side = tk.Frame(self.root, bg=t.bg_side, width=232)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.sidebar = side

        top = tk.Frame(side, bg=t.bg_side)
        top.pack(fill="x", padx=14, pady=(16, 10))
        self.new_btn = self._button(top, "＋  新建会话", self._on_new_session,
                                    primary=True)
        self.new_btn.pack(fill="x")

        tk.Label(side, text="历史会话", bg=t.bg_side, fg=t.fg_dim,
                 font=t.font(-1), anchor="w").pack(fill="x", padx=16,
                                                   pady=(10, 4))

        wrap = tk.Frame(side, bg=t.bg_side)
        wrap.pack(fill="both", expand=True, padx=(10, 6))
        self.sess_canvas = tk.Canvas(wrap, bg=t.bg_side, highlightthickness=0,
                                     bd=0)
        self.sess_canvas.pack(side="left", fill="both", expand=True)
        self.sess_inner = tk.Frame(self.sess_canvas, bg=t.bg_side)
        self.sess_window = self.sess_canvas.create_window(
            (0, 0), window=self.sess_inner, anchor="nw")
        self.sess_inner.bind(
            "<Configure>",
            lambda _e: self.sess_canvas.configure(
                scrollregion=self.sess_canvas.bbox("all")))
        self.sess_canvas.bind(
            "<Configure>",
            lambda e: self.sess_canvas.itemconfigure(self.sess_window,
                                                     width=e.width))
        self.sess_canvas.bind_all("<MouseWheel>", self._on_sidebar_wheel,
                                 add="+")

        bottom = tk.Frame(side, bg=t.bg_side)
        bottom.pack(fill="x", side="bottom", padx=14, pady=14)
        self._button(bottom, "设置", self._open_settings).pack(
            side="left", fill="x", expand=True)
        self._button(bottom, "主题", self._toggle_theme).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

    def _on_sidebar_wheel(self, event) -> None:
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return
        w = widget
        while w is not None:
            if w is self.sess_canvas:
                self.sess_canvas.yview_scroll(int(-event.delta / 120), "units")
                break
            w = getattr(w, "master", None)

    def _refresh_sessions(self) -> None:
        t = self.theme
        for child in self.sess_inner.winfo_children():
            child.destroy()
        sessions = store.list_sessions()
        if not sessions:
            tk.Label(self.sess_inner, text="暂无历史会话", bg=t.bg_side,
                     fg=t.fg_dim, font=t.font(-1)).pack(pady=12)
            return
        for item in sessions:
            self._session_row(self.sess_inner, item)

    def _session_row(self, parent, item: dict) -> None:
        t = self.theme
        active = item["id"] == self.session_id
        row = tk.Frame(parent, bg=t.bubble_user if active else t.bg_side,
                       cursor="hand2")
        row.pack(fill="x", pady=1)
        lbl = tk.Label(row, text=item["title"][:26], bg=row["bg"],
                       fg=t.fg if active else t.fg_dim, font=t.font(-1),
                       anchor="w", justify="left", padx=8, pady=6)
        lbl.pack(fill="x", side="left", expand=True)
        del_btn = tk.Label(row, text="✕", bg=row["bg"], fg=t.fg_dim,
                           font=t.font(-3), padx=6, cursor="hand2")
        del_btn.pack(side="right")

        def open_session(_e, sid=item["id"]):
            self._load_session(sid)

        def remove(_e, sid=item["id"]):
            store.delete_session(sid)
            if sid == self.session_id:
                self._on_new_session()
            else:
                self._refresh_sessions()

        for w in (row, lbl):
            w.bind("<Button-1>", open_session)
        del_btn.bind("<Button-1>", remove)

    # ---------- 顶栏 ----------

    def _build_header(self, parent) -> None:
        t = self.theme
        head = tk.Frame(parent, bg=t.bg)
        head.pack(fill="x", padx=20, pady=(14, 8))
        self.header = head

        left = tk.Frame(head, bg=t.bg)
        left.pack(side="left", fill="x", expand=True)
        self.title_lbl = tk.Label(left, text="新会话", bg=t.bg, fg=t.fg,
                                  font=t.font(3, bold=True), anchor="w")
        self.title_lbl.pack(fill="x")
        self.meta_lbl = tk.Label(left, text="", bg=t.bg, fg=t.fg_dim,
                                 font=t.font(-1), anchor="w")
        self.meta_lbl.pack(fill="x")

        right = tk.Frame(head, bg=t.bg)
        right.pack(side="right")
        self.dir_btn = self._button(right, "选择目录", self._choose_dir)
        self.dir_btn.pack(side="left")
        self.stop_btn = self._button(right, "停止", self._on_stop,
                                     danger=True)
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.stop_btn.configure(state="disabled")

    # ---------- 聊天区 ----------

    def _build_chat(self, parent) -> None:
        t = self.theme
        frame = tk.Frame(parent, bg=t.bg)
        frame.pack(fill="both", expand=True, padx=(20, 8), pady=(0, 6))

        self.chat = tk.Text(frame, bg=t.bg, fg=t.fg, bd=0,
                            highlightthickness=0, wrap="word",
                            font=t.font(), padx=8, pady=6,
                            insertwidth=0, cursor="arrow",
                            spacing1=1, spacing2=3, spacing3=3)
        self.chat.pack(side="left", fill="both", expand=True)
        self.chat.configure(state="disabled")

        self.scroll = ttk.Scrollbar(frame, orient="vertical",
                                    command=self.chat.yview,
                                    style="CN.Vertical.TScrollbar")
        self.scroll.pack(side="right", fill="y")
        self.chat.configure(yscrollcommand=self.scroll.set)

        self._configure_chat_tags()
        self.chat.bind("<MouseWheel>", self._on_chat_wheel)

    def _on_chat_wheel(self, event) -> None:
        self.chat.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _configure_chat_tags(self) -> None:
        t = self.theme
        md.configure_tags(self.chat, t)
        self.chat.tag_configure(
            "role_user", font=t.font(1, bold=True), foreground=t.accent,
            spacing1=12, lmargin1=10)
        self.chat.tag_configure(
            "role_ai", font=t.font(1, bold=True), foreground=t.fg_dim,
            spacing1=12, lmargin1=10)
        self.chat.tag_configure(
            "user_block", background=t.bubble_user, lmargin1=16, lmargin2=16,
            rmargin=16, spacing1=4, spacing3=10)
        self.chat.tag_configure("ai_block", lmargin1=16, lmargin2=16,
                                rmargin=10, spacing3=8)
        self.chat.tag_configure("tool_head", font=t.font(-1, mono=True),
                                foreground=t.fg_dim, lmargin1=22,
                                spacing1=6)
        self.chat.tag_configure(
            "tool_body", font=t.font(-1, mono=True), foreground=t.fg_dim,
            background=t.bubble_tool, lmargin1=34, lmargin2=34, rmargin=16,
            spacing1=1, spacing3=6)
        self.chat.tag_configure("err", foreground=t.error,
                                font=t.font(-1))
        self.chat.tag_configure("sysnote", foreground=t.fg_dim,
                                font=t.font(-1), lmargin1=16)
        self.chat.tag_configure("think", foreground=t.thinking_fg,
                                font=(t.ui, t.size, "italic"), lmargin1=22,
                                lmargin2=22, spacing1=3)

    # ---------- 输入区 ----------

    def _build_input(self, parent) -> None:
        t = self.theme
        outer = tk.Frame(parent, bg=t.bg)
        outer.pack(fill="x", padx=20, pady=(4, 16))
        self.input_outer = outer

        border = tk.Frame(outer, bg=t.border, bd=0)
        border.pack(fill="x")
        box = tk.Frame(border, bg=t.bg_input)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        self.input_box = box

        self.entry = tk.Text(box, height=3, bg=t.bg_input, fg=t.fg, bd=0,
                             highlightthickness=0, wrap="word",
                             font=t.font(), padx=12, pady=10,
                             insertbackground=t.fg)
        self.entry.pack(fill="x", side="top")
        self.entry.bind("<Return>", self._on_entry_return)
        self.entry.bind("<Shift-Return>", lambda _e: None)
        self.entry.bind("<Control-v>", lambda _e: self.entry.event_generate(
            "<<Paste>>"))
        self.entry.bind("<KeyRelease>", lambda _e: self._autosize_entry())

        bar = tk.Frame(box, bg=t.bg_input)
        bar.pack(fill="x", padx=10, pady=(0, 8))
        self.hint = tk.Label(bar, text="Enter 发送 · Shift+Enter 换行 · Esc 停止",
                             bg=t.bg_input, fg=t.fg_dim, font=t.font(-2),
                             anchor="w")
        self.hint.pack(side="left")
        self.send_btn = self._button(bar, "发送", self._on_send, primary=True)
        self.send_btn.pack(side="right")

    def _autosize_entry(self) -> None:
        try:
            lines = int(self.entry.index("end-1c").split(".")[0])
        except (ValueError, tk.TclError):
            return
        lines = max(3, min(lines, 10))
        if lines != int(self.entry.cget("height")):
            self.entry.configure(height=lines)

    # ---------- 通用控件 ----------

    def _button(self, parent, text: str, command, primary: bool = False,
                danger: bool = False) -> tk.Button:
        t = self.theme
        if primary:
            bg, fg, active = t.accent, t.accent_fg, t.accent
        elif danger:
            bg, fg, active = t.bg_side, t.error, t.border
        else:
            bg, fg, active = t.bg_side, t.fg, t.border
        btn = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                        activebackground=active, activeforeground=fg,
                        font=t.font(-1), bd=0, relief="flat",
                        padx=12, pady=6, cursor="hand2",
                        highlightthickness=0)
        if danger:
            btn.configure(bg=t.bg)
        return btn

    # ================= 事件循环 =================

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.root.after(50, self._pump)

    def _handle(self, kind: str, payload) -> None:
        handler = getattr(self, f"_ev_{kind}", None)
        if handler:
            handler(payload)
        elif kind == "stderr":
            self._sysnote(str(payload), dim=True)

    def _ev_init(self, data: dict) -> None:
        self.cli_session_id = data.get("session_id") or self.cli_session_id
        model = data.get("model") or "默认模型"
        cwd = data.get("cwd") or self.cfg.get("work_dir", "")
        self.meta_lbl.configure(text=f"{model}   ·   {cwd}")
        self.dir_btn.configure(text="选择目录")

    def _ev_turn_start(self, data: dict) -> None:
        self.busy = True
        self._reset_stream()
        self.pending_assistant_msg = {"role": "assistant", "text": "",
                                      "tools": [], "thinking": ""}
        self.stop_btn.configure(state="normal")
        self.send_btn.configure(state="disabled", text="发送中")

    def _ev_message_start(self, data: dict) -> None:
        self._close_region()
        self._ensure_ai_header()

    def _ensure_ai_header(self) -> None:
        if self.header_open:
            return
        self._writable()
        self.chat.insert("end", "\nClaude\n", ("role_ai",))
        self._readonly()
        self.header_open = True

    # ---------- 流式区域渲染 ----------
    #
    # 区域起于 block_start，内容每次整体重绘（保证行内标记与列表渲染正确），
    # 未完成的尾行单独增量绘制，避免每个字符都触发整段重排。

    def _ensure_region(self) -> None:
        if self.block_start is not None:
            return
        self._ensure_ai_header()
        self.stream_buf = ""
        self.block_start = self.chat.index("end-1c")
        self.partial_start = None

    def _render_region(self) -> None:
        if self.block_start is None:
            return
        self._writable()
        self.chat.delete(self.block_start, "end-1c")
        md.render_markdown(self.chat, self.stream_buf, self.theme,
                           self.link_sink, ("ai_block",))
        self._readonly()
        self.partial_start = None
        self._scroll_bottom()

    def _render_partial(self) -> None:
        self._writable()
        if self.partial_start is not None:
            self.chat.delete(self.partial_start, "end-1c")
        else:
            self.partial_start = self.chat.index("end-1c")
        tail = self.stream_buf.rsplit("\n", 1)[-1]
        tags = ("ai_block", "md_codeblock") if self.stream_in_code \
            else ("ai_block",)
        md._insert_inline(self.chat, tail, self.theme, self.link_sink, tags)
        self._readonly()
        self._scroll_bottom()

    def _close_region(self) -> None:
        if self.block_start is None:
            return
        self._render_region()
        self.stream_buf = ""
        self.block_start = None
        self.partial_start = None

    def _ev_text_delta(self, data: dict) -> None:
        piece = data.get("text", "")
        if not piece:
            return
        self._ensure_region()
        self.stream_buf += piece
        if "\n" in piece:
            self._render_region()
        else:
            self._render_partial()

    def _ev_block_end(self, data: dict) -> None:
        text = data.get("text", "")
        if self.block_start is None and text:
            # 未经流式增量的块（例如非流式后端），整段渲染
            self._ensure_region()
            self.stream_buf = text
        final_text = self.stream_buf or text
        self._close_region()
        if self.pending_assistant_msg is not None:
            self.pending_assistant_msg["text"] += final_text

    def _ev_thinking_delta(self, data: dict) -> None:
        if not self.cfg.get("show_thinking"):
            return
        if self.block_start is not None:
            return
        self._ensure_ai_header()
        self._writable()
        if not self.think_open:
            self.chat.insert("end", "❯ 思考中…\n", ("think",))
            self.think_open = True
        self.chat.insert("end", data.get("text", ""), ("think",))
        self._readonly()
        self._scroll_bottom()

    def _ev_thinking_end(self, data: dict) -> None:
        if not self.think_open:
            return
        self._writable()
        self.chat.insert("end", "\n", ("think",))
        self._readonly()
        self.think_open = False

    def _ev_permission_request(self, data: dict) -> None:
        request_id = data.get("request_id")
        summary = data.get("summary") or ""
        tool_name = data.get("tool_name") or "工具"
        self._sysnote(f"请求使用 {tool_name}：{summary}", dim=True)
        allow = PermissionDialog.ask(self, tool_name, summary)
        self.engine.respond_permission(request_id, allow)
        self._sysnote("已允许该操作。" if allow else "已拒绝该操作。", dim=True)

    def _ev_tool_use_start(self, data: dict) -> None:
        self._close_region()
        self._writable()
        self.chat.insert("end", "\n⏺ " + str(data.get("name", "工具")) + "\n",
                         ("tool_head",))
        self._readonly()
        self._scroll_bottom()

    def _ev_tool_use(self, data: dict) -> None:
        self._close_region()
        name = data.get("name", "")
        args = self._format_tool_args(name, data.get("input") or {})
        self._writable()
        self.chat.insert("end", args + "\n", ("tool_body",))
        self._readonly()
        if self.pending_assistant_msg is not None:
            self.pending_assistant_msg["tools"].append(
                {"name": name, "input": data.get("input") or {},
                 "result": ""})
        self._scroll_bottom()

    def _ev_tool_result(self, data: dict) -> None:
        text = (data.get("text") or "").strip()
        is_error = data.get("is_error")
        lines = text.split("\n")
        shown = lines[:MAX_TOOL_LINES]
        body = "\n".join("  " + ln for ln in shown)
        if len(lines) > MAX_TOOL_LINES:
            body += f"\n  …（共 {len(lines)} 行）"
        if is_error:
            body = body or "  （执行失败）"
        self._writable()
        self.chat.insert("end", "  ⎿ " + body.lstrip() + "\n",
                         ("err",) if is_error else ("tool_body",))
        self._readonly()
        if self.pending_assistant_msg is not None \
                and self.pending_assistant_msg["tools"]:
            self.pending_assistant_msg["tools"][-1]["result"] = text[:2000]
        self._scroll_bottom()

    def _ev_assistant_text(self, data: dict) -> None:
        """未经流式渲染的完整文本（回退路径）。"""
        self._ensure_ai_header()
        self._writable()
        self.chat.tag_add("ai_block", "end-1c", "end")
        md.render_markdown(self.chat, data.get("text", ""), self.theme,
                           self.link_sink, ("ai_block",))
        self._readonly()
        if self.pending_assistant_msg is not None:
            self.pending_assistant_msg["text"] += data.get("text", "")
        self._scroll_bottom()

    def _ev_message_stop(self, data: dict) -> None:
        self._close_region()
        self._readonly()

    def _ev_result(self, data: dict) -> None:
        if data.get("session_id"):
            self.cli_session_id = data["session_id"]
        if data.get("is_error"):
            detail = str(data.get("result") or "")
            if "not logged in" in detail.lower() or "/login" in detail:
                self._sysnote(
                    "还没有登录 Claude Code，界面无法代你登录。"
                    "请在命令行里执行一次 `claude`，输入 /login 完成登录，"
                    "然后回到这里重新发送。", error=True)
            else:
                self._sysnote("本轮执行出错：" + detail[:400], error=True)
        self._finalize_turn()

    def _ev_exit(self, data: dict) -> None:
        if self.busy:
            self._finalize_turn()
        else:
            self.stop_btn.configure(state="disabled")
            self.send_btn.configure(state="normal", text="发送")
        if self.messages:
            self._sysnote(f"会话进程已退出（代码 {data.get('code')}）。"
                          "下次发送会自动重启。", dim=True)

    # ================= 发送 / 停止 =================

    def _on_entry_return(self, event):
        if event.state & 0x0001:  # Shift
            return None
        self._on_send()
        return "break"

    def _on_send(self) -> None:
        if self.busy:
            return
        text = self.entry.get("1.0", "end-1c").strip()
        if not text:
            return
        if not self._ensure_engine():
            return

        self.entry.delete("1.0", "end")
        self.entry.configure(height=3)
        self._append_user(text)
        self.messages.append({"role": "user", "text": text})
        if len(self.messages) == 1:
            self.session_title = md.plain_text_of(text)[:30] or "新会话"
            self.title_lbl.configure(text=self.session_title)

        try:
            self.engine.send(text)
        except RuntimeError as exc:
            self._sysnote(str(exc), error=True)
            self.busy = False
            self.send_btn.configure(state="normal", text="发送")

    def _on_stop(self) -> None:
        if not self.busy:
            return
        self.engine.interrupt()
        self.root.after(1500, self._force_stop_if_busy)

    def _force_stop_if_busy(self) -> None:
        if not self.busy:
            return
        self.engine.stop()
        self._finalize_turn()
        self._sysnote("已中断本轮。", dim=True)

    def _finalize_turn(self) -> None:
        """收尾：落盘未完成的消息，恢复按钮状态。"""
        self._close_region()
        self.busy = False
        self.stop_btn.configure(state="disabled")
        self.send_btn.configure(state="normal", text="发送")
        if self.pending_assistant_msg is not None:
            msg = self.pending_assistant_msg
            if msg["text"].strip() or msg["tools"]:
                self.messages.append(msg)
            self.pending_assistant_msg = None
        self._persist()
        self._refresh_sessions()
        self._scroll_bottom()

    def _ensure_engine(self) -> bool:
        work_dir = self.cfg.get("work_dir") or str(store.Path.home())
        if not os.path.isdir(work_dir):
            messagebox.showerror(APP_TITLE, f"工作目录不存在：\n{work_dir}")
            return False
        try:
            self.engine.start(
                model=self.cfg.get("model") or None,
                permission_mode=self.cfg.get("permission_mode", "auto"),
                cwd=work_dir,
                resume_session=self.cli_session_id,
            )
            return True
        except RuntimeError as exc:
            self._sysnote(str(exc), error=True)
            messagebox.showerror(APP_TITLE, str(exc))
            return False

    # ================= 聊天区写入 =================

    def _writable(self) -> None:
        self.chat.configure(state="normal")

    def _readonly(self) -> None:
        self.chat.configure(state="disabled")

    def _scroll_bottom(self) -> None:
        self.chat.see("end")

    def _append_user(self, text: str) -> None:
        self._writable()
        self.chat.insert("end", "\n你\n", ("role_user",))
        for line in text.split("\n"):
            self.chat.insert("end", line + "\n", ("user_block",))
        self._readonly()
        self._scroll_bottom()

    def _sysnote(self, text: str, dim: bool = False, error: bool = False) -> None:
        self._writable()
        self.chat.insert("end", "\n" + text + "\n",
                         ("err",) if error else ("sysnote",))
        self._readonly()
        self._scroll_bottom()

    def _format_tool_args(self, name: str, args: dict) -> str:
        return self._format_tool_args_static(name, args)

    # ================= 会话管理 =================

    def _persist(self) -> None:
        store.save_session(
            session_id=self.session_id,
            title=self.session_title,
            messages=self.messages,
            cli_session_id=self.cli_session_id,
            work_dir=self.cfg.get("work_dir", ""),
        )

    def _reset_conversation(self) -> None:
        """清空流式渲染状态与链接表；messages/title 由调用方设置。"""
        self._reset_stream()
        self.link_sink.clear()

    def _on_new_session(self) -> None:
        if self.busy:
            self._sysnote("请先停止当前回合。", error=True)
            return
        self.engine.stop()
        self.session_id = store.new_session_id()
        self.cli_session_id = None
        self.session_title = "新会话"
        self.messages = []
        self._reset_conversation()
        self.title_lbl.configure(text=self.session_title)
        self.meta_lbl.configure(text=self.cfg.get("work_dir", ""))
        self._clear_chat()
        self._refresh_sessions()
        self._welcome()

    def _load_session(self, session_id: str) -> None:
        if session_id == self.session_id:
            return
        if self.busy:
            self._sysnote("请先停止当前回合。", error=True)
            return
        data = store.load_session(session_id)
        if not data:
            return
        self.engine.stop()
        self.session_id = session_id
        self.cli_session_id = data.get("cli_session_id")
        self.session_title = data.get("title") or "会话"
        self._reset_conversation()
        self.messages = data.get("messages", [])
        self.title_lbl.configure(text=self.session_title)
        self.meta_lbl.configure(text=data.get("work_dir", "")
                                or self.cfg.get("work_dir", ""))
        self._clear_chat()
        for msg in self.messages:
            self._replay(msg)
        self._refresh_sessions()
        self._scroll_bottom()

    def _clear_chat(self) -> None:
        self._writable()
        self.chat.delete("1.0", "end")
        self._readonly()

    @staticmethod
    def _format_tool_args_static(name: str, args: dict) -> str:
        if name == "Bash":
            return "  $ " + str(args.get("command", ""))[:800]
        if name in ("Read", "Write", "Edit", "NotebookEdit"):
            return "  " + str(args.get("file_path",
                                       args.get("notebook_path", "")))
        if name in ("Glob", "Grep"):
            return "  " + str(args.get("pattern", ""))
        if name == "WebFetch":
            return "  " + str(args.get("url", ""))
        if name in ("Task", "Agent"):
            return "  " + str(args.get("description", ""))
        import json as _json
        try:
            return "  " + _json.dumps(args, ensure_ascii=False)[:300]
        except (TypeError, ValueError):
            return "  " + str(args)[:300]

    def _replay(self, msg: dict) -> None:
        if msg.get("role") == "user":
            self._append_user(msg.get("text", ""))
            return
        self._writable()
        self.chat.insert("end", "\nClaude\n", ("role_ai",))
        md.render_markdown(self.chat, msg.get("text", ""), self.theme,
                           self.link_sink, ("ai_block",))
        for tool in msg.get("tools", []):
            self.chat.insert("end", "\n⏺ " + tool.get("name", "") + "\n",
                             ("tool_head",))
            self.chat.insert(
                "end", self._format_tool_args_static(
                    tool.get("name", ""), tool.get("input") or {}) + "\n",
                ("tool_body",))
            if tool.get("result"):
                lines = tool["result"].strip().split("\n")[:MAX_TOOL_LINES]
                self.chat.insert(
                    "end", "  ⎿ " + "\n".join(lines).lstrip() + "\n",
                    ("tool_body",))
        self._readonly()

    def _welcome(self) -> None:
        t = self.theme
        self._writable()
        self.chat.insert("end", "Claude 桌面版\n", ("md_h1",))
        self.chat.insert(
            "end",
            "原生中文界面，直接驱动本机的 Claude Code。\n"
            "先在上方「选择目录」指定工作目录，然后开始对话。\n",
            ("sysnote",))
        self.chat.insert("end", "\n快捷键\n", ("md_h3",))
        for tip in ("Enter 发送，Shift+Enter 换行",
                    "Esc 中断当前回合",
                    "侧栏「新建会话」开启全新上下文"):
            self.chat.insert("end", "•  " + tip + "\n", ("md_list",))
        self._readonly()

    # ================= 设置 / 主题 =================

    def _choose_dir(self) -> None:
        chosen = filedialog.askdirectory(
            title="选择工作目录", initialdir=self.cfg.get("work_dir"))
        if chosen:
            self.cfg["work_dir"] = chosen
            self.engine.stop()
            self.cli_session_id = None
            store.save_config(self.cfg)
            self.meta_lbl.configure(text=chosen)

    def _toggle_theme(self) -> None:
        self.cfg["dark"] = not bool(self.cfg.get("dark"))
        th.apply_palette(self.theme, self.cfg["dark"])
        store.save_config(self.cfg)
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        """主题（或字号）变化后重建界面，并重放当前会话。"""
        self._reset_stream()
        self.link_sink.clear()
        for child in self.root.winfo_children():
            child.destroy()
        self._build_ui()
        self._refresh_sessions()
        self.title_lbl.configure(text=self.session_title)
        self.meta_lbl.configure(text=self.cfg.get("work_dir", ""))
        if self.busy:
            self.stop_btn.configure(state="normal")
            self.send_btn.configure(state="disabled", text="发送中")
        if self.messages:
            for msg in self.messages:
                self._replay(msg)
            self._scroll_bottom()
        else:
            self._welcome()

    def _open_settings(self) -> None:
        SettingsDialog(self)

    def _on_close(self) -> None:
        self.engine.stop()
        self.root.destroy()


# ===================== 权限确认对话框 =====================

class PermissionDialog(tk.Toplevel):
    """模态确认框：claude 请求使用某个工具时弹出。"""

    @classmethod
    def ask(cls, app: ClaudeDesktopApp, tool_name: str, summary: str) -> bool:
        dialog = cls(app, tool_name, summary)
        app.root.wait_window(dialog)
        return dialog.result

    def __init__(self, app: ClaudeDesktopApp, tool_name: str, summary: str):
        super().__init__(app.root)
        self.result = False
        t = app.theme
        self.title("需要确认")
        self.configure(bg=t.bg)
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._deny)

        tk.Label(self, text=f"Claude 请求使用 {tool_name}", bg=t.bg, fg=t.fg,
                 font=t.font(1, bold=True), anchor="w").pack(
                     fill="x", padx=20, pady=(18, 6))

        box = tk.Text(self, height=6, width=64, bg=t.code_bg, fg=t.fg,
                      font=t.font(-1, mono=True), bd=1, relief="solid",
                      wrap="word", padx=10, pady=8, highlightthickness=0)
        box.insert("1.0", summary or "（无参数）")
        box.configure(state="disabled")
        box.pack(fill="both", expand=True, padx=20)

        btns = tk.Frame(self, bg=t.bg)
        btns.pack(fill="x", padx=20, pady=16)
        app._button(btns, "拒绝", self._deny).pack(side="right")
        app._button(btns, "允许", self._allow, primary=True).pack(
            side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _e: self._deny())
        self.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() -
                                      self.winfo_width()) // 2
        y = app.root.winfo_rooty() + 160
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.focus_force()

    def _allow(self) -> None:
        self.result = True
        self.destroy()

    def _deny(self) -> None:
        self.result = False
        self.destroy()


# ===================== 设置对话框 =====================

class SettingsDialog(tk.Toplevel):
    def __init__(self, app: ClaudeDesktopApp):
        super().__init__(app.root)
        self.app = app
        t = app.theme
        self.title("设置")
        self.configure(bg=t.bg)
        self.resizable(False, False)
        self.transient(app.root)

        pad = {"padx": 18, "pady": 6}
        tk.Label(self, text="工作目录", bg=t.bg, fg=t.fg, anchor="w",
                 font=t.font(0, bold=True)).pack(fill="x", **pad)
        row = tk.Frame(self, bg=t.bg)
        row.pack(fill="x", padx=18)
        self.dir_var = tk.StringVar(value=app.cfg.get("work_dir", ""))
        tk.Entry(row, textvariable=self.dir_var, font=t.font(),
                 bg=t.bg_input, fg=t.fg, bd=1, relief="solid",
                 highlightthickness=0).pack(side="left", fill="x",
                                            expand=True, ipady=4)
        app._button(row, "浏览", self._pick_dir).pack(side="left", padx=(8, 0))

        tk.Label(self, text="模型（留空使用 CLI 默认）", bg=t.bg, fg=t.fg,
                 anchor="w", font=t.font(0, bold=True)).pack(fill="x", **pad)
        self.model_var = tk.StringVar(value=app.cfg.get("model", ""))
        tk.Entry(self, textvariable=self.model_var, font=t.font(),
                 bg=t.bg_input, fg=t.fg, bd=1, relief="solid",
                 highlightthickness=0).pack(fill="x", padx=18, ipady=4)

        tk.Label(self, text="权限模式", bg=t.bg, fg=t.fg, anchor="w",
                 font=t.font(0, bold=True)).pack(fill="x", **pad)
        self.mode_var = tk.StringVar()
        cur = app.cfg.get("permission_mode", "auto")
        for label, value in eng.PERMISSION_MODES.items():
            if value == cur:
                self.mode_var.set(label)
        if not self.mode_var.get():
            self.mode_var.set("自动判断")
        om = tk.OptionMenu(self, self.mode_var, *eng.PERMISSION_MODES.keys())
        om.configure(bg=t.bg_side, fg=t.fg, font=t.font(-1), bd=0,
                     highlightthickness=0, activebackground=t.border)
        om["menu"].configure(bg=t.bg_side, fg=t.fg, font=t.font(-1))
        om.pack(fill="x", padx=18)

        self.think_var = tk.BooleanVar(value=bool(app.cfg.get("show_thinking")))
        tk.Checkbutton(self, text="显示思考过程", variable=self.think_var,
                       bg=t.bg, fg=t.fg, font=t.font(-1),
                       activebackground=t.bg, selectcolor=t.bg_side,
                       anchor="w").pack(fill="x", padx=14, pady=(10, 0))

        tk.Label(self, text="字号", bg=t.bg, fg=t.fg, anchor="w",
                 font=t.font(0, bold=True)).pack(fill="x", **pad)
        self.size_var = tk.IntVar(value=int(app.cfg.get("font_size", 11)))
        tk.Scale(self, from_=9, to=18, orient="horizontal",
                 variable=self.size_var, bg=t.bg, fg=t.fg,
                 troughcolor=t.bg_side, font=t.font(-2),
                 highlightthickness=0, bd=0, length=300).pack(
                     fill="x", padx=18)

        btns = tk.Frame(self, bg=t.bg)
        btns.pack(fill="x", padx=18, pady=16)
        app._button(btns, "取消", self.destroy).pack(side="right")
        app._button(btns, "保存", self._save, primary=True).pack(
            side="right", padx=(0, 8))

        self.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - self.winfo_width()) // 2
        y = app.root.winfo_rooty() + 120
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()

    def _pick_dir(self) -> None:
        chosen = filedialog.askdirectory(title="选择工作目录",
                                         initialdir=self.dir_var.get() or None)
        if chosen:
            self.dir_var.set(chosen)

    def _save(self) -> None:
        app = self.app
        old_work_dir = app.cfg.get("work_dir")
        app.cfg["work_dir"] = self.dir_var.get().strip()
        app.cfg["model"] = self.model_var.get().strip()
        app.cfg["permission_mode"] = eng.PERMISSION_MODES.get(
            self.mode_var.get(), "auto")
        app.cfg["show_thinking"] = bool(self.think_var.get())
        new_size = int(self.size_var.get())
        size_changed = new_size != int(app.cfg.get("font_size", 11))
        app.cfg["font_size"] = new_size
        store.save_config(app.cfg)

        if app.cfg["work_dir"] != old_work_dir:
            app.engine.stop()
            app.cli_session_id = None

        self.destroy()

        if size_changed:
            app.theme.size = new_size
            app.theme.mono_size = new_size
            app.theme.small = max(8, new_size - 1)
            app._rebuild_ui()
        else:
            app._configure_chat_tags()


def main() -> None:
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    ClaudeDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
