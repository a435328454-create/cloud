# -*- coding: utf-8 -*-
"""开发期目视检查：填充模拟对话，截图保存后退出。不参与发布。"""
import os, time, tkinter as tk
from PIL import ImageGrab
import app as app_mod

root = tk.Tk()
a = app_mod.ClaudeDesktopApp(root)

a._reset_stream()
a._append_user("帮我看看这个项目的结构，顺便解释一下流式渲染是怎么做的。")
a._handle("turn_start", {})
a._handle("init", {"session_id": "s1", "model": "Sonnet 5",
                   "cwd": r"E:\cloud\claude-desktop", "tools": []})
a._handle("message_start", {"message_id": "m1"})
for piece in ["我先看一下目录结构，然后说明渲染流程。\n\n",
              "1. 收到 `text_delta` 时累加进缓冲区\n",
              "2. 未完成的尾行单独绘制\n",
              "3. 遇换行整段重排，代价可控\n\n",
              "```python\ndef render(self):\n"
              "    self.chat.delete(self.block_start, 'end-1c')\n```\n\n",
              "最后写入历史，避免重放时二次渲染。"]:
    a._handle("text_delta", {"index": 0, "text": piece})
a._handle("tool_use_start", {"name": "Bash", "id": "t1"})
a._handle("tool_use", {"name": "Bash", "id": "t1",
                       "input": {"command": "ls -la engine.py app.py"}})
a._handle("tool_result", {"tool_use_id": "t1", "is_error": False,
                          "text": "engine.py   18342 bytes\napp.py      24711 bytes"})
a._handle("block_end", {"index": 0, "text": ""})
a._handle("result", {"subtype": "success", "is_error": False, "session_id": "s1"})
root.update()

def shoot(path):
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
    print("saved", path)

print('LIGHT messages:', len(a.messages))
root.after(700, lambda: (shoot(os.path.join(os.getcwd(), "shot_light.png")),
                         root.quit()))
root.mainloop()

a.cfg["dark"] = True
import theme as th
th.apply_palette(a.theme, True)
a._rebuild_ui()
print('DARK messages:', len(a.messages), 'title:', a.session_title)
root.update()
root.after(700, lambda: (shoot(os.path.join(os.getcwd(), "shot_dark.png")),
                         root.quit()))
root.mainloop()
root.destroy()
