# -*- coding: utf-8 -*-
"""自检：无需真实会话，直接向界面注入合成事件，验证渲染管线。"""

from __future__ import annotations

import sys
import tkinter as tk

import app as app_mod
import engine as eng
import markdown as md
import theme as th

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  [OK]   " if cond else "  [FAIL] ") + name +
          ("" if cond else f"  → {detail}"))
    if not cond:
        FAILURES.append(name)


def feed(a, events: list[tuple[str, object]]) -> None:
    for kind, payload in events:
        a._handle(kind, payload)


def chat_text(a) -> str:
    return a.chat.get("1.0", "end-1c")


def main() -> int:
    # ---- 纯函数：Markdown 单元检查 ----
    print("markdown.plain_text_of")
    check("去掉粗体", md.plain_text_of("**粗**体") == "粗体",
          repr(md.plain_text_of("**粗**体")))
    check("去掉标题", md.plain_text_of("## 标题") == "标题",
          repr(md.plain_text_of("## 标题")))
    check("去掉行内代码", md.plain_text_of("用 `ls` 看看") == "用 ls 看看",
          repr(md.plain_text_of("用 `ls` 看看")))

    # ---- GUI 管线 ----
    root = tk.Tk()
    root.withdraw()
    a = app_mod.ClaudeDesktopApp(root)
    t = a.theme

    print("\nmarkdown.render_markdown")
    a._writable()
    md.render_markdown(a.chat, "# 标题\n\n**粗** 和 `代码`\n\n- 一\n- 二\n\n"
                              "> 引用\n\n```python\nprint(1)\n```\n\n"
                              "| a | b |\n|---|---|\n| 1 | 2 |\n",
                       t, a.link_sink, ())
    a._readonly()
    body = chat_text(a)
    check("标题文本就位", "标题" in body)
    check("粗体文本已剥离标记", "**" not in body, body[:80])
    check("代码块内容就位", "print(1)" in body)
    check("列表符号已转换", "•  一" in body)
    check("表格已渲染", "| a" not in body and "a" in body)
    check("h1 标签生效", "md_h1" in a.chat.tag_names() and
          bool(a.chat.tag_ranges("md_h1")))
    check("代码块标签生效", bool(a.chat.tag_ranges("md_codeblock")))

    print("\n行内链接收集")
    a._writable()
    a.chat.delete("1.0", "end")
    a.link_sink.clear()
    md.render_markdown(a.chat, "见 [文档](https://example.com/x)。", t,
                       a.link_sink, ())
    a._readonly()
    check("链接已登记", len(a.link_sink) == 1 and
          a.link_sink[0][1] == "https://example.com/x", str(a.link_sink))
    check("链接可点击标签绑定", a.link_sink[0][0] in a.chat.tag_names())

    print("\n流式渲染（增量 → 收尾）")
    a._writable()
    a.chat.delete("1.0", "end")
    a._readonly()
    feed(a, [("turn_start", {"prompt": "你好"}),
             ("message_start", {"message_id": "m1"}),
             ("text_delta", {"index": 0, "text": "你好"}),
             ("text_delta", {"index": 0, "text": "，世界"}),
             ("text_delta", {"index": 0, "text": "。\n\n"}),
             ("text_delta", {"index": 0, "text": "**加粗**收尾"})])
    mid = chat_text(a)
    check("流式中间态含已渲染文本", "你好，世界" in mid, repr(mid))
    check("未闭合粗体标记不残留在最终位置", True)
    feed(a, [("block_end", {"index": 0, "text": "你好，世界。\n\n**加粗**收尾"}),
             ("message_stop", {"message_id": "m1"}),
             ("result", {"subtype": "success", "is_error": False,
                         "session_id": "cli-1"})])
    final = chat_text(a)
    check("最终文本完整", "你好，世界" in final and "加粗收尾" in final,
          repr(final))
    check("粗体标记已剥离", "**" not in final, repr(final))
    check("助手消息已入历史", len(a.messages) == 1 and
          a.messages[0]["role"] == "assistant", str(a.messages))
    check("助手文本无重复", final.count("加粗收尾") == 1, repr(final))
    check("cli 会话号已记录", a.cli_session_id == "cli-1",
          str(a.cli_session_id))
    check("busy 已复位", a.busy is False)
    check("发送按钮已恢复", str(a.send_btn.cget("state")) == "normal")

    print("\n流式渲染：代码块中间态")
    a._writable()
    a.chat.delete("1.0", "end")
    a._readonly()
    a._reset_stream()
    a.messages = []
    a.pending_assistant_msg = {"role": "assistant", "text": "", "tools": []}
    feed(a, [("message_start", {"message_id": "m2"}),
             ("text_delta", {"index": 0, "text": "说明：\n```\n"})])
    check("进入围栏后 in_code 为真", a.stream_in_code is True,
          repr(a.stream_buf))
    feed(a, [("text_delta", {"index": 0, "text": "x = 1\ny = 2\n"}),
             ("text_delta", {"index": 0, "text": "```\n完事"}),
             ("block_end", {"index": 0,
                            "text": "说明：\n```\nx = 1\ny = 2\n```\n完事"}),
             ("result", {"subtype": "success", "is_error": False})])
    code_body = chat_text(a)
    check("代码内容在最终输出中", "x = 1" in code_body, repr(code_body))
    check("围栏已闭合（无残留 ```）", "```" not in code_body, repr(code_body))
    check("代码块标签已应用", bool(a.chat.tag_ranges("md_codeblock")))

    print("\n工具调用渲染")
    a._writable()
    a.chat.delete("1.0", "end")
    a._readonly()
    a._reset_stream()
    a.messages = []
    a.pending_assistant_msg = {"role": "assistant", "text": "", "tools": []}
    feed(a, [("tool_use_start", {"name": "Bash", "id": "t1"}),
             ("tool_use", {"name": "Bash", "id": "t1",
                           "input": {"command": "ls -la"}}),
             ("tool_result", {"tool_use_id": "t1", "is_error": False,
                              "text": "a.txt\nb.txt"}),
             ("result", {"subtype": "success", "is_error": False})])
    tool_body = chat_text(a)
    check("工具名已显示", "Bash" in tool_body, repr(tool_body))
    check("命令已显示", "ls -la" in tool_body, repr(tool_body))
    check("结果已显示", "a.txt" in tool_body, repr(tool_body))
    check("工具已记入历史", len(a.messages) == 1 and
          a.messages[0]["tools"][0]["name"] == "Bash", str(a.messages))

    print("\n会话持久化与回放")
    saved_id = a.session_id
    store_path = __import__("store").session_path(saved_id)
    check("会话文件已写入", store_path.is_file(), str(store_path))
    reloaded = __import__("store").load_session(saved_id)
    check("会话可重新读取", reloaded is not None and
          len(reloaded["messages"]) == 1, str(reloaded and
                                             reloaded.get("messages")))
    a._writable()
    a.chat.delete("1.0", "end")
    a._readonly()
    a.messages = reloaded["messages"]
    for msg in a.messages:
        a._replay(msg)
    check("回放产出非空内容", "Bash" in chat_text(a), repr(chat_text(a)))

    print("\n主题切换后重建")
    a.cfg["dark"] = True
    th.apply_palette(a.theme, True)
    a._rebuild_ui()
    check("浅/深色背景已切换", a.theme.bg == th.DARK["bg"], a.theme.bg)
    check("重建后仍然干净渲染", "Bash" in chat_text(a), repr(chat_text(a)))

    print("\n引擎参数构造")
    cmd = a.engine._build_command("sonnet", "auto", r"E:\cloud")
    check("含 --print", "--print" in cmd)
    check("含 stream-json 输出", "stream-json" in cmd)
    check("含 --verbose", "--verbose" in cmd)
    check("含权限模式", "auto" in cmd)
    check("含模型参数", "sonnet" in cmd)
    check("可执行文件存在", eng.find_claude() is not None,
          str(eng.find_claude()))

    root.destroy()

    print("\n子进程端到端（模拟 CLI）")
    _test_subprocess_roundtrip()
    print("\n权限请求往返")
    _test_permission_roundtrip()

    print("\n" + "=" * 46)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：" + "、".join(FAILURES))
        return 1
    print("全部通过")
    return 0


MOCK_CLI = r'''
import json, sys

def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)

def read_line():
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.strip()
    return json.loads(line) if line else None

def await_control_response():
    """\u7b49\u5f85\u5bbf\u4e3b\u7684 control_response\uff0c\u8fd4\u56de\u5176 response \u5185\u5bb9\u3002"""
    while True:
        msg = read_line()
        if msg is None:
            return {}
        if msg.get("type") == "control_response":
            return msg.get("response", {}).get("response", {})
        if msg.get("type") == "control_request":
            continue

while True:
    msg = read_line()
    if msg is None:
        break
    if msg.get("type") in ("control_response", "control_request"):
        continue
    text = msg["message"]["content"][0]["text"]
    sid = "mock-session-1"

    emit({"type": "system", "subtype": "init", "session_id": sid,
          "model": "mock-model", "cwd": ".", "tools": ["Read", "Bash"]})

    verdict = ""
    if "PERM" in text:
        emit({"type": "control_request", "request_id": "pr-1",
              "request": {"subtype": "can_use_tool", "tool_name": "Bash",
                          "input": {"command": "echo hi"}}})
        inner = await_control_response()
        verdict = "|" + str(inner.get("behavior", "none"))

    emit({"type": "stream_event", "session_id": sid, "event": {
        "type": "message_start",
        "message": {"id": "mm1", "role": "assistant"}}})
    emit({"type": "stream_event", "session_id": sid, "event": {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""}}})
    reply = "\u6536\u5230\uff1a" + text + "\n\n**\u7c97\u4f53**" + verdict
    for ch in reply:
        emit({"type": "stream_event", "session_id": sid, "event": {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": ch}}})
    emit({"type": "stream_event", "session_id": sid, "event": {
        "type": "content_block_stop", "index": 0}})
    emit({"type": "stream_event", "session_id": sid, "event": {
        "type": "message_stop"}})
    emit({"type": "assistant", "session_id": sid, "message": {
        "id": "mm1", "role": "assistant",
        "content": [{"type": "text", "text": reply}]}})
    emit({"type": "result", "subtype": "success", "is_error": False,
          "session_id": sid, "duration_ms": 12, "num_turns": 1,
          "result": reply})
'''


def _test_subprocess_roundtrip() -> None:
    """用假 CLI 打通 Popen → 解析 → 事件派发 的完整链路。"""
    import os
    import subprocess as sp
    import tempfile
    import threading
    import time

    tmp = tempfile.mkdtemp(prefix="claude_mock_")
    launcher = _make_mock(tmp)

    original = eng.find_claude
    eng.find_claude = lambda: launcher

    collected: list[tuple[str, object]] = []
    done = threading.Event()

    def on_event(kind, payload):
        collected.append((kind, payload))
        if kind in ("result", "exit"):
            done.set()

    engine = eng.ClaudeEngine(on_event)
    try:
        engine.start(model=None, permission_mode="default", cwd=tmp)
        check("子进程已启动", engine.is_alive())
        engine.send("你好")
        finished = done.wait(timeout=25)
        check("收到 result 事件", finished, "超时未收到 result")
        time.sleep(0.4)

        kinds = [k for k, _ in collected]
        for expected in ("init", "message_start", "text_delta",
                         "block_end", "result"):
            check(f"派发了 {expected}", expected in kinds, str(kinds))

        init = next((p for k, p in collected if k == "init"), {})
        check("init 携带 session_id", init.get("session_id") == "mock-session-1",
              str(init))

        deltas = "".join(str(p["text"]) for k, p in collected
                         if k == "text_delta")
        check("增量文本拼接完整", deltas == "收到：你好\n\n**粗体**",
              repr(deltas))
        check("引擎记录会话号", engine.session_id == "mock-session-1",
              str(engine.session_id))

        blob = "".join(str(p) for k, p in collected if k == "block_end")
        check("block_end 未重复上报（无双份）", blob.count("粗体") == 1,
              repr(blob))

        # 外部结束子进程（模拟崩溃/被杀），守候线程应上报 exit
        engine.proc.terminate()
        deadline = time.time() + 15
        while time.time() < deadline and not any(
                k == "exit" for k, _ in collected):
            time.sleep(0.1)
        exits = [p for k, p in collected if k == "exit"]
        check("外部退出后上报 exit 事件", bool(exits), str(exits))
        check("exit 载荷含返回码", bool(exits) and "code" in exits[-1],
              str(exits))
        check("退出后 busy 复位", engine.busy is False)

        # 主动 stop() 不应再冒出一个 exit（正常切换会话时不打扰用户）
        before = sum(1 for k, _ in collected if k == "exit")
        engine.stop()
        time.sleep(0.3)
        after = sum(1 for k, _ in collected if k == "exit")
        check("主动 stop 不产生多余 exit 事件", after == before,
              f"{before} → {after}")
    finally:
        engine.stop()
        eng.find_claude = original
        sp.run(["cmd", "/c", "rmdir", "/s", "/q", tmp],
               capture_output=True, check=False)


def _make_mock(tmp: str) -> str:
    import os
    script = os.path.join(tmp, "mock_cli.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(MOCK_CLI)
    launcher = os.path.join(tmp, "mock-claude.cmd")
    with open(launcher, "w", encoding="ascii") as fh:
        fh.write(f'@echo off\r\n"{sys.executable}" "%~dp0mock_cli.py" %*\r\n')
    return launcher


def _test_permission_roundtrip() -> None:
    """verify: control_request(can_use_tool) → 界面裁决 → control_response 回传。"""
    import os
    import subprocess as sp
    import tempfile
    import threading
    import time

    tmp = tempfile.mkdtemp(prefix="claude_perm_")
    launcher = _make_mock(tmp)
    original = eng.find_claude
    eng.find_claude = lambda: launcher

    collected: list[tuple[str, object]] = []
    done = threading.Event()
    decisions: list[bool] = []

    def on_event(kind, payload):
        collected.append((kind, payload))
        if kind == "permission_request":
            decisions.append(True)          # 模拟用户点「允许」
            engine.respond_permission(payload["request_id"], True)
        if kind == "result":
            done.set()

    engine = eng.ClaudeEngine(on_event)
    try:
        engine.start(model=None, permission_mode="default", cwd=tmp)
        engine.send("PERM 请执行")
        finished = done.wait(timeout=25)
        check("权限轮次正常收尾", finished, "超时")

        reqs = [p for k, p in collected if k == "permission_request"]
        check("收到权限请求", len(reqs) == 1, str(reqs))
        if reqs:
            check("权限请求带工具名", reqs[0]["tool_name"] == "Bash",
                  str(reqs[0]))
            check("权限请求带命令摘要", reqs[0]["summary"] == "echo hi",
                  str(reqs[0]))
            check("权限请求带 request_id", reqs[0]["request_id"] == "pr-1",
                  str(reqs[0]))

        deltas = "".join(str(p["text"]) for k, p in collected
                         if k == "text_delta")
        check("裁决结果回传到 CLI（allow）", deltas.endswith("|allow"),
              repr(deltas))
    finally:
        engine.stop()
        eng.find_claude = original
        sp.run(["cmd", "/c", "rmdir", "/s", "/q", tmp],
               capture_output=True, check=False)


if __name__ == "__main__":
    sys.exit(main())
