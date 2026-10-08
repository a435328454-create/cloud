# 技术决策记录

## claude-desktop

### D1 用 Python + Tkinter，不用 Web 前端

- 决策：桌面 GUI 选 Tkinter。
- 理由：目标是本机桌面工具，零第三方依赖、免打包、免 Node 工具链，`pythonw` 双击即用。
- 影响：UI 能力受 Tkinter 限制，Markdown 需自行渲染（见 `markdown.py`），不使用 React/WebView。

### D2 用 stream-json 协议驱动 claude CLI

- 决策：长驻一个 `claude` 子进程，以 JSON Lines 双向通信，而非每次调用起新进程。
- 理由：支持多轮上下文复用、流式增量输出、权限交互往返。
- 影响：必须带 `--verbose`（否则 `stream-json` 输出被 CLI 拒绝）；需要处理子进程生命周期与退出事件。

### D3 纯标准库，不引入第三方依赖

- 决策：全程只用 Python 标准库。
- 理由：降低本机部署与维护成本。
- 影响：Markdown、主题、配置存储均自行实现；新增功能优先考虑标准库方案。

### D4 数据存 %APPDATA%\ClaudeDesktopCN

- 决策：配置与会话记录写入 APPDATA 下的应用目录，不写在项目目录里。
- 理由：程序目录可只读，用户数据应与代码分离。
- 影响：换机器不携带历史会话；清理需手动删 APPDATA 目录。

---

## 工作根目录：E:\cloud

### D5 记忆文件放在工作根目录

- 决策：`AGENTS.md` / `MEMORY_INDEX.md` 等 6 个记忆文件放在 `E:\cloud` 根，描述整个工作区；子项目信息汇总在其中，暂不为子项目单独建记忆文件。
- 理由：目前仅一个子项目，单层结构更易维护。
- 影响：子项目增多（≥3 个或结构复杂）时，再考虑下放到各子项目目录。
