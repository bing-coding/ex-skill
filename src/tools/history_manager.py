"""
对话历史管理器
将聊天记录持久化到本地文件，支持跨会话记忆。

目录结构：
  data/chat_history/
    sessions/
      2026-03-31.json     ← 每天一个文件，当天所有对话追加进去
      2026-04-01.json
    ...

可独立运行（供 SKILL.md 通过 Bash 调用），也可作为模块导入（供 chain.py 调用）。
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).parent.parent.parent
_HISTORY_DIR = _PROJECT_ROOT / "data" / "chat_history"
_SESSIONS_DIR = _HISTORY_DIR / "sessions"


def _ensure_dirs() -> None:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def get_today_session_id() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_session_path(session_id: str) -> Path:
    return _SESSIONS_DIR / f"{session_id}.json"


def list_sessions() -> list[str]:
    """列出所有会话 ID（按时间倒序）"""
    _ensure_dirs()
    return sorted(
        [p.stem for p in _SESSIONS_DIR.glob("*.json")],
        reverse=True,
    )


def load_session(session_id: str) -> list[dict[str, Any]]:
    """加载指定会话的消息列表"""
    path = get_session_path(session_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []


def save_turn(
    user_msg: str,
    assistant_msg: str,
    session_id: str | None = None,
) -> None:
    """追加一轮对话（user + assistant）到当天会话文件"""
    _ensure_dirs()
    sid = session_id or get_today_session_id()
    path = get_session_path(sid)
    existing = load_session(sid)
    now = datetime.now().isoformat(timespec="seconds")
    existing.append({"timestamp": now, "role": "user", "content": user_msg})
    existing.append({"timestamp": now, "role": "assistant", "content": assistant_msg})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def save_session_batch(
    turns: list[dict[str, str]],
    session_id: str | None = None,
) -> None:
    """批量写入一次会话的所有消息（chat_loop 结束时调用）"""
    if not turns:
        return
    _ensure_dirs()
    sid = session_id or get_today_session_id()
    path = get_session_path(sid)
    existing = load_session(sid)
    now = datetime.now().isoformat(timespec="seconds")
    for t in turns:
        existing.append({
            "timestamp": t.get("timestamp", now),
            "role": t["role"],
            "content": t["content"],
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def load_recent_as_messages(
    n_sessions: int = 2,
    max_turns: int = 20,
) -> list[dict[str, str]]:
    """
    加载最近 N 个会话，转换为 LLM messages 格式（不含 system 消息）。
    用于在新 Python 会话启动时注入历史上下文，让 LLM 有"记忆"。

    Returns:
        [{"role": "user"/"assistant", "content": "..."}, ...]
    """
    sessions = list_sessions()[:n_sessions]
    if not sessions:
        return []
    all_turns: list[dict[str, Any]] = []
    for sid in reversed(sessions):  # 时间正序
        all_turns.extend(load_session(sid))
    recent = all_turns[-(max_turns * 2):]
    return [{"role": t["role"], "content": t["content"]} for t in recent]


def load_recent_as_text(
    n_sessions: int = 3,
    max_turns: int = 30,
) -> str:
    """
    加载历史记录为人类可读文本。
    供 SKILL.md 通过 Bash 调用后注入 Claude 上下文。
    """
    sessions = list_sessions()[:n_sessions]
    if not sessions:
        return "（暂无历史对话记录）"

    lines = ["[跨会话记忆 - 你们之前聊过的内容]"]
    for sid in reversed(sessions):
        turns = load_session(sid)
        if not turns:
            continue
        lines.append(f"\n── {sid} ──")
        recent_turns = turns[-(max_turns * 2):]
        for t in recent_turns:
            role_label = "你" if t["role"] == "user" else "TA"
            ts = t.get("timestamp", "")[:16].replace("T", " ")
            snippet = t["content"][:200] + ("…" if len(t["content"]) > 200 else "")
            lines.append(f"[{ts}] {role_label}：{snippet}")

    return "\n".join(lines)


def get_stats() -> dict[str, Any]:
    """返回历史记录统计信息"""
    sessions = list_sessions()
    total_turns = sum(len(load_session(sid)) // 2 for sid in sessions)
    return {
        "total_sessions": len(sessions),
        "total_turns": total_turns,
        "sessions": sessions,
        "latest": sessions[0] if sessions else None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="对话历史管理器")
    parser.add_argument(
        "--action",
        choices=["load", "save-turn", "list", "stats"],
        default="load",
        help="操作类型",
    )
    parser.add_argument("--recent", type=int, default=3, help="加载最近 N 个会话")
    parser.add_argument("--max-turns", type=int, default=30, help="每个会话最多加载 N 轮")
    parser.add_argument("--user", type=str, default="", help="用户消息（save-turn 用）")
    parser.add_argument("--assistant", type=str, default="", help="前任回复（save-turn 用）")
    parser.add_argument("--session", type=str, default=None, help="会话 ID（默认当天日期）")
    args = parser.parse_args()

    if args.action == "load":
        print(load_recent_as_text(n_sessions=args.recent, max_turns=args.max_turns))

    elif args.action == "save-turn":
        if not args.user or not args.assistant:
            print("错误：需要同时提供 --user 和 --assistant 参数")
        else:
            save_turn(args.user, args.assistant, session_id=args.session)
            print(f"已保存到会话 {args.session or get_today_session_id()}")

    elif args.action == "list":
        stats = get_stats()
        print(f"共 {stats['total_sessions']} 个会话，{stats['total_turns']} 轮对话")
        for sid in stats["sessions"]:
            turns = len(load_session(sid)) // 2
            print(f"  {sid}  （{turns} 轮）")

    elif args.action == "stats":
        stats = get_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
