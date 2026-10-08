# 项目记忆索引

工作根目录：`E:\cloud`（确认为长期工作根目录，2026-10-08）

## 记忆文件

| 文件 | 作用 | 何时读 |
| --- | --- | --- |
| `CLAUDE.md` | 入口，Claude Code 自动加载 | 始终 |
| `AGENTS.md` | 目录级开发规则 | 始终 |
| `MEMORY_INDEX.md` | 本文件，记忆索引 | 始终 |
| `NEXT_TASKS.md` | 待办与优先级 | 优先读取 |
| `PROJECT_CONTEXT.md` | 架构、技术栈、启动方式 | 涉及架构/启动时 |
| `PROGRESS.md` | 进度、已完成、已知问题 | 涉及进度/历史时 |
| `DECISIONS.md` | 技术选型与重大决策 | 涉及选型/结构时 |

## 子项目

| 项目 | 路径 | 技术栈 | 状态 |
| --- | --- | --- | --- |
| claude-desktop | `claude-desktop/` | Python 3 + Tkinter，纯标准库 | 可运行，自检全通过 |

## 当前关键状态

- 尚无进行中的高优先级任务，见 `NEXT_TASKS.md`。
- `claude-desktop` 功能完整，无已知阻断性缺陷。
- 工作根目录未初始化 git。

## 常用命令

```bash
cd /e/cloud/claude-desktop && PYTHONIOENCODING=utf-8 python selftest.py 2>&1 | head -c 4000
```
