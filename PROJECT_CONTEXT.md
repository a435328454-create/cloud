# 项目上下文

## 工作根目录：E:\cloud

长期开发工作根目录，按子项目分目录组织。当前子项目见 `MEMORY_INDEX.md`。

---

## 子项目：claude-desktop

### 定位

Claude 桌面版（中文界面）。用 Python + Tkinter 做的 GUI，通过 `stream-json` 协议驱动本机 `claude` CLI，实现流式对话界面。

### 技术栈

- Python 3（使用了 `X | None` 语法与 `from __future__ import annotations`，需 3.10+）
- Tkinter（`tkinter` / `ttk`），无任何第三方依赖，纯标准库
- 与 CLI 的通信：JSON Lines over 子进程 stdin/stdout

### 文件结构

| 文件 | 行数 | 职责 |
| --- | --- | --- |
| `app.py` | 1019 | 主窗口、UI 构建、事件分发、会话管理 |
| `engine.py` | 475 | CLI 桥接：定位可执行文件、子进程管理、stream-json 解析、权限往返 |
| `selftest.py` | 405 | 自检：注入合成事件验证渲染管线与引擎协议，含模拟 CLI 子进程端到端测试 |
| `markdown.py` | 200 | Markdown → Tkinter Text 标签渲染 |
| `store.py` | 110 | 配置与会话记录持久化 |
| `theme.py` | 68 | 配色与字体选择（中文字体回退链） |
| `_visual.py` | 53 | 视觉/截图辅助脚本 |

### 关键机制

- **CLI 参数**：见 `engine.py` 的 `BASE_ARGS`。`stream-json` 输出必须搭配 `--verbose`，否则 CLI 拒绝启动。使用 `--permission-prompt-tool stdio` 做权限往返。
- **权限模式**：`PERMISSION_MODES` 映射中文名 → CLI 模式（default / auto / acceptEdits / plan / bypassPermissions）。
- **可执行文件定位**：`engine.find_claude()` 依次查环境变量 `CLAUDE_CODE_EXECPATH`、PATH、`%LOCALAPPDATA%\Claude-3p\claude-code\<version>\claude.exe`。
- **事件模型**：引擎通过 `on_event(kind, payload)` 回调推事件，界面用 `queue.Queue` 跨线程收集，`root.after` 泵送。
- **数据目录**：`%APPDATA%\ClaudeDesktopCN\`，内含 `config.json` 与 `sessions/*.json`。

### 启动与验证

```bash
cd /e/cloud/claude-desktop && pythonw app.py
```

```bash
cd /e/cloud/claude-desktop && PYTHONIOENCODING=utf-8 python selftest.py 2>&1 | head -c 4000
```

也可双击 `启动.bat` / `自检.bat`（均带 `chcp 65001`）。
