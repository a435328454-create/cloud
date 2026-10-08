# -*- coding: utf-8 -*-
"""Claude Code CLI 桥接层。

负责：定位 claude 可执行文件、以 stream-json 协议双向通信、
解析事件流并翻译成界面可消费的简单事件。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

IS_WINDOWS = sys.platform == "win32"

# stream-json 输出必须以 --verbose 启动，否则 CLI 会拒绝
BASE_ARGS = ["--print", "--verbose", "--output-format", "stream-json",
             "--input-format", "stream-json", "--include-partial-messages",
             "--permission-prompt-tool", "stdio"]

PERMISSION_MODES = {
    "默认（每次询问）": "default",
    "自动判断": "auto",
    "自动接受文件编辑": "acceptEdits",
    "计划模式（只读）": "plan",
    "跳过全部确认": "bypassPermissions",
}


def find_claude() -> str | None:
    """定位 claude 可执行文件，返回绝对路径或 None。"""
    candidates: list[str] = []

    env_exe = os.environ.get("CLAUDE_CODE_EXECPATH")
    if env_exe:
        candidates.append(env_exe)

    for name in ("claude.exe", "claude.cmd", "claude.bat", "claude"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    local = os.environ.get("LOCALAPPDATA")
    if local:
        base = Path(local) / "Claude-3p" / "claude-code"
        if base.is_dir():
            for version_dir in sorted(base.iterdir(), reverse=True):
                exe = version_dir / "claude.exe"
                if exe.is_file():
                    candidates.append(str(exe))

    for cand in candidates:
        if cand and Path(cand).is_file():
            return str(Path(cand))
    return None


class ClaudeEngine:
    """长驻一个 claude 子进程，双向流式对话。

    事件通过 on_event(kind, payload) 回调推送给界面线程。
    """

    def __init__(self, on_event: Callable[[str, Any], None]):
        self.on_event = on_event
        self.proc: subprocess.Popen | None = None
        self.session_id: str | None = None
        self.busy = False
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._watcher: threading.Thread | None = None
        self._exit_emitted = True
        # 块级流式缓冲：{(message_id, block_index): {"type":..., "text":...}}
        self._blocks: dict[tuple[str, int], dict[str, Any]] = {}
        self._streamed_messages: set[str] = set()

    # ---------- 进程生命周期 ----------

    def _build_command(self, model: str | None, permission_mode: str,
                       cwd: str) -> list[str]:
        exe = find_claude()
        if not exe:
            raise RuntimeError(
                "找不到 claude 可执行文件。请确认 Claude Code 已安装，"
                "并把它所在目录加入 PATH。"
            )
        cmd = [exe] + list(BASE_ARGS)
        if model:
            cmd += ["--model", model]
        cmd += ["--permission-mode", permission_mode]
        return cmd

    def start(self, model: str | None, permission_mode: str, cwd: str,
              resume_session: str | None = None) -> None:
        """启动（或复用）子进程。"""
        with self._lock:
            alive = self.proc is not None and self.proc.poll() is None
            same_cwd = alive and getattr(self, "_cwd", None) == cwd
            if alive and same_cwd and resume_session in (None, self.session_id):
                return
            self._kill_locked()

            cmd = self._build_command(model, permission_mode, cwd)
            if resume_session:
                cmd += ["--resume", resume_session]

            creationflags = 0
            if IS_WINDOWS:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            env = os.environ.copy()
            env.setdefault("CLAUDE_CODE_ENTRYPOINT", "claude-desktop-cn")

            try:
                self.proc = subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=env,
                    creationflags=creationflags,
                )
            except OSError as exc:
                raise RuntimeError(f"启动 claude 失败：{exc}") from exc

            self._cwd = cwd
            self._exit_emitted = False
            if resume_session:
                self.session_id = resume_session

        self._reader = threading.Thread(target=self._read_stdout,
                                        args=(self.proc,), daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._read_stderr,
                                               args=(self.proc,), daemon=True)
        self._stderr_reader.start()
        self._watcher = threading.Thread(target=self._watch_exit,
                                         args=(self.proc,), daemon=True)
        self._watcher.start()

    def _watch_exit(self, proc: subprocess.Popen) -> None:
        """独立守候进程退出。

        stdout 迭代在某些情况下会卡住（例如包装脚本被终止后孙进程仍持有管道），
        因此退出事件不能依赖读取线程收尾，否则界面会永远停在「发送中」。
        """
        code = proc.wait()
        with self._lock:
            if self.proc is proc and not self._exit_emitted:
                self._exit_emitted = True
                self.busy = False
                self.on_event("exit", {"code": code})

    def _kill_locked(self) -> None:
        self._exit_emitted = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None
        self._blocks.clear()
        self._streamed_messages.clear()

    def stop(self) -> None:
        with self._lock:
            self._kill_locked()

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ---------- 发送 ----------

    def send(self, text: str) -> None:
        proc = self.proc
        if not proc or proc.poll() is not None:
            raise RuntimeError("会话进程未运行")
        payload = {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        }
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            try:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError(f"写入会话失败：{exc}") from exc
        self.busy = True
        self.on_event("turn_start", {"prompt": text})

    def interrupt(self) -> None:
        """中断当前回合。"""
        self._write_line({
            "type": "control_request",
            "request_id": f"int-{time.time_ns()}",
            "request": {"subtype": "interrupt"},
        })

    def respond_permission(self, request_id: str, allow: bool,
                           message: str | None = None) -> None:
        """回答 can_use_tool 权限请求。"""
        if allow:
            inner: dict[str, Any] = {"behavior": "allow"}
        else:
            inner = {"behavior": "deny",
                     "message": message or "用户拒绝了该操作"}
        self._write_line({
            "type": "control_response",
            "response": {"subtype": "success", "request_id": request_id,
                         "response": inner},
        })

    def _write_line(self, payload: dict) -> None:
        proc = self.proc
        if not proc or proc.poll() is not None:
            return
        try:
            line = json.dumps(payload, ensure_ascii=False)
            with self._lock:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    # ---------- 读取 ----------

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stderr:  # type: ignore[union-attr]
                line = line.strip()
                if line:
                    self.on_event("stderr", line)
        except Exception:
            pass

    def _read_stdout(self, proc: subprocess.Popen) -> None:
        """逐行读取事件流。退出事件由 _watch_exit 统一上报，此处不重复发。"""
        try:
            for raw in proc.stdout:  # type: ignore[union-attr]
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    self.on_event("stderr", raw[:500])
                    continue
                try:
                    self._dispatch(event)
                except Exception as exc:  # 单条事件解析失败不应拖垮整个会话
                    self.on_event("stderr", f"事件解析异常：{exc}")
        except (ValueError, OSError):
            pass

    def _dispatch(self, event: dict) -> None:
        etype = event.get("type")
        sid = event.get("session_id")
        if sid:
            self.session_id = sid

        if etype == "control_request":
            self._dispatch_control_request(event)
            return

        if etype == "control_response":
            return

        if etype == "system":
            if event.get("subtype") == "init":
                self.on_event("init", {
                    "session_id": sid,
                    "model": event.get("model"),
                    "tools": event.get("tools", []),
                    "cwd": event.get("cwd"),
                })
            return

        if etype == "stream_event":
            self._dispatch_stream_event(event.get("event") or {})
            return

        if etype == "assistant":
            self._dispatch_assistant(event)
            return

        if etype == "user":
            self._dispatch_tool_results(event)
            return

        if etype == "result":
            self.busy = False
            self.on_event("result", {
                "subtype": event.get("subtype"),
                "is_error": event.get("is_error", False),
                "result": event.get("result"),
                "duration_ms": event.get("duration_ms"),
                "num_turns": event.get("num_turns"),
                "total_cost_usd": event.get("total_cost_usd"),
                "usage": event.get("usage") or {},
                "session_id": sid,
            })
            return

    def _dispatch_control_request(self, event: dict) -> None:
        request = event.get("request") or {}
        if request.get("subtype") != "can_use_tool":
            return
        tool_name = request.get("tool_name") or "工具"
        tool_input = request.get("input") or {}
        self.on_event("permission_request", {
            "request_id": event.get("request_id"),
            "tool_name": tool_name,
            "input": tool_input,
            "summary": _summarize_tool(tool_name, tool_input),
        })

    def _dispatch_stream_event(self, ev: dict) -> None:
        kind = ev.get("type")
        index = ev.get("index")

        if kind == "message_start":
            msg_id = (ev.get("message") or {}).get("id", "")
            self._current_msg_id = msg_id
            self.on_event("message_start", {"message_id": msg_id})
            return

        msg_id = getattr(self, "_current_msg_id", "")

        if kind == "content_block_start":
            block = ev.get("content_block") or {}
            btype = block.get("type")
            key = (msg_id, index)
            if btype == "tool_use":
                self._blocks[key] = {"type": "tool_use", "name": block.get("name"),
                                     "id": block.get("id"), "json": ""}
                self.on_event("tool_use_start", {
                    "name": block.get("name"), "id": block.get("id"),
                })
            else:
                self._blocks[key] = {"type": btype, "text": ""}
                if btype == "text":
                    self._streamed_messages.add(msg_id)
                self.on_event("block_start", {"index": index, "block_type": btype})
            return

        if kind == "content_block_delta":
            delta = ev.get("delta") or {}
            dtype = delta.get("type")
            key = (msg_id, index)
            slot = self._blocks.setdefault(key, {"type": "text", "text": ""})

            if dtype == "text_delta":
                piece = delta.get("text", "")
                slot["text"] = slot.get("text", "") + piece
                self._streamed_messages.add(msg_id)
                self.on_event("text_delta", {"index": index, "text": piece})
            elif dtype == "thinking_delta":
                piece = delta.get("thinking", "")
                slot["text"] = slot.get("text", "") + piece
                self.on_event("thinking_delta", {"index": index, "text": piece})
            elif dtype == "input_json_delta":
                slot["json"] = slot.get("json", "") + delta.get("partial_json", "")
            return

        if kind == "content_block_stop":
            key = (msg_id, index)
            slot = self._blocks.pop(key, None)
            if not slot:
                return
            if slot.get("type") == "tool_use":
                raw = slot.get("json") or "{}"
                try:
                    tool_input = json.loads(raw)
                except json.JSONDecodeError:
                    tool_input = {"_raw": raw}
                self.on_event("tool_use", {
                    "name": slot.get("name"), "id": slot.get("id"),
                    "input": tool_input,
                })
            elif slot.get("type") == "text":
                self.on_event("block_end", {"index": index,
                                            "text": slot.get("text", "")})
            elif slot.get("type") == "thinking":
                self.on_event("thinking_end", {"index": index})
            return

        if kind == "message_stop":
            self.on_event("message_stop", {"message_id": msg_id})
            return

    def _dispatch_assistant(self, event: dict) -> None:
        """完整 assistant 消息。若该消息的文本已通过流式增量渲染过，则跳过文本，避免重复。"""
        message = event.get("message") or {}
        msg_id = message.get("id", "")
        already = msg_id in self._streamed_messages

        for block in message.get("content", []):
            btype = block.get("type")
            if btype == "text" and not already:
                self.on_event("assistant_text", {"text": block.get("text", "")})
            elif btype == "tool_use":
                # 已在 content_block_stop 中上报过
                continue

    def _dispatch_tool_results(self, event: dict) -> None:
        message = event.get("message") or {}
        for block in message.get("content", []):
            if block.get("type") != "tool_result":
                continue
            content = block.get("content")
            text = _flatten_tool_result(content)
            self.on_event("tool_result", {
                "tool_use_id": block.get("tool_use_id"),
                "is_error": bool(block.get("is_error")),
                "text": text,
            })


def _summarize_tool(name: str, args: dict) -> str:
    """把工具调用压成一行人类可读的描述，用于权限确认框。"""
    if name == "Bash":
        return str(args.get("command", ""))[:600]
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        path = args.get("file_path") or args.get("notebook_path") or ""
        return str(path)
    if name in ("Glob", "Grep"):
        return str(args.get("pattern", ""))
    if name == "WebFetch":
        return str(args.get("url", ""))
    if name in ("Task", "Agent"):
        return str(args.get("description", ""))
    if name == "WebSearch":
        return str(args.get("query", ""))
    try:
        return json.dumps(args, ensure_ascii=False)[:400]
    except (TypeError, ValueError):
        return str(args)[:400]


def _flatten_tool_result(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    parts.append("[图片]")
                else:
                    parts.append(json.dumps(item, ensure_ascii=False)[:300])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False)[:1000]
