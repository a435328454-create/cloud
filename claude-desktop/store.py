# -*- coding: utf-8 -*-
"""本地配置与会话记录的持久化。"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ClaudeDesktopCN"
CONFIG_FILE = APP_DIR / "config.json"
SESSIONS_DIR = APP_DIR / "sessions"

DEFAULT_CONFIG: dict[str, Any] = {
    "work_dir": str(Path.home()),
    "model": "",
    "permission_mode": "default",
    "font_size": 11,
    "show_thinking": False,
}


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    ensure_dirs()
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.is_file():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    ensure_dirs()
    try:
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---------- 会话记录 ----------

def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def save_session(session_id: str, title: str, messages: list[dict],
                 cli_session_id: str | None, work_dir: str) -> None:
    ensure_dirs()
    data = {
        "id": session_id,
        "title": title,
        "updated_at": time.time(),
        "cli_session_id": cli_session_id,
        "work_dir": work_dir,
        "messages": messages,
    }
    try:
        session_path(session_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_session(session_id: str) -> dict | None:
    path = session_path(session_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_sessions() -> list[dict]:
    ensure_dirs()
    out = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "id": data.get("id", path.stem),
            "title": data.get("title") or "未命名会话",
            "updated_at": data.get("updated_at", 0),
        })
    out.sort(key=lambda item: item["updated_at"], reverse=True)
    return out


def delete_session(session_id: str) -> None:
    try:
        session_path(session_id).unlink(missing_ok=True)
    except OSError:
        pass
