"""
LLM 主链路
串联所有模块：StaticMemory → RAGRetriever → PromptBuilder → Qwen API → Formatter
支持命令行直接运行和作为模块调用两种使用方式。
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Any

import dashscope
from dashscope import Generation

# 确保项目根目录在 sys.path 中（命令行运行时需要）
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.persona_engine.prompt_builder import get_prompt_builder, PromptBuilder
from src.decision_output.formatter import parse_output, DecisionOutput
from src.memory.static_memory import load_corrections, save_corrections
from src.tools.history_manager import (
    load_recent_as_messages,
    save_turn as _history_save_turn,
    save_session_batch,
    get_stats as _history_stats,
)


_DEFAULT_MODEL = "qwen-max"
_DEFAULT_TOP_K = 3


class DigitalCloneChain:
    """
    前任.skill 主链路。
    组合 PromptBuilder + DashScope API + OutputFormatter，
    支持单次问答（run）和多轮聊天（chat）两种模式。
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        top_k: int = _DEFAULT_TOP_K,
        prompt_builder: PromptBuilder | None = None,
    ):
        key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        if not key:
            raise ValueError(
                "未设置 DASHSCOPE_API_KEY。\n"
                "请运行：$env:DASHSCOPE_API_KEY='your_key'（Windows）\n"
                "或：export DASHSCOPE_API_KEY='your_key'（macOS/Linux）"
            )
        dashscope.api_key = key
        self.model = model
        self.top_k = top_k
        self._builder = prompt_builder or get_prompt_builder()
        # 多轮对话历史（chat 模式专用）
        self._history: list[dict[str, str]] = []
        # 跨会话持久化：本次 chat_loop 新增的轮次（用于结束时批量写盘）
        self._new_turns: list[dict[str, str]] = []

    # ------------------------------------------------------------------ #
    # 单次问答（原有行为）
    # ------------------------------------------------------------------ #

    def run(self, user_input: str) -> DecisionOutput:
        """
        单次问答：每次调用独立，不保留上下文。
        适合针对特定问题的分析型查询。
        """
        if not user_input.strip():
            raise ValueError("用户输入不能为空")

        system_prompt, _ = self._builder.build(user_input, top_k=self.top_k)
        raw_text = self._call_llm(system_prompt, user_input, history=[])
        return parse_output(raw_text, user_input=user_input)

    def run_with_preview(self, user_input: str) -> tuple[DecisionOutput, str]:
        """运行并同时返回 Prompt 预览（用于调试）"""
        preview = self._builder.preview(user_input, top_k=self.top_k)
        output = self.run(user_input)
        return output, preview

    # ------------------------------------------------------------------ #
    # 多轮聊天（新增）
    # ------------------------------------------------------------------ #

    def chat(self, user_input: str) -> DecisionOutput:
        """
        多轮聊天：保留本次会话的对话历史。
        前任会「记得」这次对话中你之前说过的话，以及历史文件里跨会话的内容。
        """
        if not user_input.strip():
            raise ValueError("输入不能为空")

        system_prompt, _ = self._builder.build(user_input, top_k=self.top_k)
        raw_text = self._call_llm(system_prompt, user_input, history=self._history)

        # 更新内存历史
        self._history.append({"role": "user", "content": user_input})
        self._history.append({"role": "assistant", "content": raw_text})

        # 记录本轮新内容（等 chat_loop 结束时或每 N 轮批量写盘）
        from datetime import datetime
        now = datetime.now().isoformat(timespec="seconds")
        self._new_turns.append({"timestamp": now, "role": "user", "content": user_input})
        self._new_turns.append({"timestamp": now, "role": "assistant", "content": raw_text})

        # 每 5 轮自动持久化一次
        if len(self._new_turns) >= 10:
            self._flush_history()

        return parse_output(raw_text, user_input=user_input)

    def _flush_history(self) -> None:
        """将 _new_turns 写入磁盘并清空缓冲"""
        if self._new_turns:
            save_session_batch(self._new_turns)
            self._new_turns = []

    def load_persistent_history(self, n_sessions: int = 2, max_turns: int = 20) -> int:
        """
        从磁盘加载最近 N 个会话的历史，注入到当前 _history。
        返回加载的轮数。
        """
        past = load_recent_as_messages(n_sessions=n_sessions, max_turns=max_turns)
        if past:
            self._history = past + self._history
        return len(past) // 2

    def clear_history(self) -> None:
        """清空当前内存会话历史，开始全新对话（不删除磁盘文件）"""
        self._history = []
        self._new_turns = []

    @property
    def history_turns(self) -> int:
        """返回当前内存中已进行的对话轮数（含历史注入）"""
        return len(self._history) // 2

    def chat_loop(self, resume: bool = True) -> None:
        """
        交互式聊天循环（命令行使用）。

        Args:
            resume: 是否自动加载历史会话记忆（默认 True）

        指令：
          /quit /q   退出并保存
          /clear     清空本次内存历史（磁盘不删）
          /memory    显示跨会话记忆统计
          /save      立即写盘
        """
        name = self._builder._memory.name
        user_name = self._builder._memory.user_name or "你"

        # 加载历史记忆
        loaded_turns = 0
        if resume:
            loaded_turns = self.load_persistent_history(n_sessions=2, max_turns=20)

        print(f"\n{'='*50}")
        print(f"  和 {name} 聊天中")
        if loaded_turns > 0:
            print(f"  已加载 {loaded_turns} 轮历史记忆（TA 记得你们之前聊过的内容）")
        else:
            print(f"  这是你们的第一次对话")
        print(f"  /quit 退出并保存  /clear 重置  /memory 查看记忆")
        print(f"{'='*50}\n")

        try:
            while True:
                try:
                    raw = input(f"{user_name}：").strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if not raw:
                    continue

                if raw in ("/quit", "/q", "quit", "exit"):
                    break

                if raw == "/clear":
                    self.clear_history()
                    print(f"[本次对话历史已清空，磁盘记录保留]\n")
                    continue

                if raw == "/memory":
                    stats = _history_stats()
                    print(
                        f"[历史记忆：共 {stats['total_sessions']} 个会话，"
                        f"{stats['total_turns']} 轮对话，"
                        f"最近：{stats['latest'] or '无'}]\n"
                    )
                    continue

                if raw == "/save":
                    self._flush_history()
                    print(f"[已保存到磁盘]\n")
                    continue

                try:
                    output = self.chat(raw)
                    print(f"\n{name}：{output.decision.strip()}")
                    print(f"\n  ── 旁观者注：{output.retrospective.strip()}\n")
                except RuntimeError as e:
                    print(f"\n[API 错误：{e}]\n")
        finally:
            # 退出时无论如何写盘
            self._flush_history()
            new = len(self._history) // 2 - loaded_turns
            if new > 0:
                print(f"\n[本次新聊了 {new} 轮，已保存到历史记录]")
            print(f"[对话结束]")

    def add_correction(
        self,
        wrong: str,
        correct: str,
        scene: str = "通用场景",
    ) -> None:
        """
        记录一条行为纠正，写入 data/corrections.json。
        下次调用 run() 时自动生效（需重建 PromptBuilder 单例）。

        Args:
            wrong: 数字分身不应该有的行为描述
            correct: 应该如何表现
            scene: 场景标签（可选，用于标注纠正适用的情境）

        示例：
            chain.add_correction(
                scene="被要求加班",
                wrong="委婉答应后再找理由推脱",
                correct="直接说不行，同时给出替代方案",
            )
        """
        import datetime
        corrections = load_corrections()
        max_id = max(
            (int(c.get("id", "c0").lstrip("c") or 0) for c in corrections),
            default=0,
        )
        corrections.append({
            "id": f"c{str(max_id + 1).zfill(3)}",
            "scene": scene,
            "wrong": wrong,
            "correct": correct,
            "timestamp": datetime.date.today().isoformat(),
        })
        save_corrections(corrections)
        # 使下一次 build() 时重新加载 corrections
        from src.memory.static_memory import _instance as _sm_instance
        if _sm_instance is not None:
            _sm_instance.corrections = corrections
        print(f"[Chain] Correction 已记录：[{scene}] 不应「{wrong}」，应「{correct}」")

    def _call_llm(
        self,
        system_prompt: str,
        user_input: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """
        调用 DashScope Generation API。
        history 为多轮对话的历史消息（user/assistant 交替），
        不包含 system 消息（system 始终作为第一条注入）。
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})

        response = Generation.call(
            model=self.model,
            messages=messages,
            result_format="message",
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"LLM API 调用失败：{response.code} - {response.message}"
            )
        return response.output.choices[0].message.content


# ------------------------------------------------------------------ #
# 全局单例
# ------------------------------------------------------------------ #

_chain_instance: DigitalCloneChain | None = None


def get_chain(
    api_key: str | None = None,
    model: str = _DEFAULT_MODEL,
    top_k: int = _DEFAULT_TOP_K,
) -> DigitalCloneChain:
    """获取全局链路单例。当 api_key / model / top_k 任一非默认时重建实例。"""
    global _chain_instance
    needs_rebuild = (
        _chain_instance is None
        or api_key is not None
        or _chain_instance.model != model
        or _chain_instance.top_k != top_k
    )
    if needs_rebuild:
        _chain_instance = DigitalCloneChain(api_key=api_key, model=model, top_k=top_k)
    return _chain_instance


# ------------------------------------------------------------------ #
# 便捷函数（Workbuddy / OpenClaw Skill 调用入口）
# ------------------------------------------------------------------ #

def ask(user_input: str, api_key: str | None = None) -> str:
    """
    单次问答接口，返回格式化纯文本。
    适合 Workbuddy/OpenClaw 平台直接调用（无上下文）。
    """
    chain = get_chain(api_key=api_key)
    output = chain.run(user_input)
    return output.to_display()


def chat_session(
    user_input: str,
    history: list[dict[str, str]] | None = None,
    api_key: str | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """
    带历史的多轮聊天接口，适合平台/Web 集成。

    Args:
        user_input: 本轮用户输入
        history: 上轮返回的 history（首次传 None 或 []）
        api_key: 可选

    Returns:
        (回复文本, 更新后的 history)
        调用方需自行保存 history 并在下次调用时传入。

    示例：
        history = []
        reply, history = chat_session("你最近怎么样", history=history)
        reply, history = chat_session("那你还想我吗", history=history)
    """
    chain = get_chain(api_key=api_key)
    # 临时挂载外部 history（不污染 chain 内部 _history）
    system_prompt, _ = chain._builder.build(user_input, top_k=chain.top_k)
    raw_text = chain._call_llm(system_prompt, user_input, history=history or [])
    output = parse_output(raw_text, user_input=user_input)

    new_history = list(history or [])
    new_history.append({"role": "user", "content": user_input})
    new_history.append({"role": "assistant", "content": raw_text})

    return output.to_display(), new_history


# ------------------------------------------------------------------ #
# 命令行入口
# ------------------------------------------------------------------ #

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="前任.skill CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 开启聊天模式（推荐）
  python -m src.llm_chain.chain --chat

  # 单次问答
  python -m src.llm_chain.chain --input "TA 当时为什么突然不回消息"

  # 调试：显示完整 Prompt
  python -m src.llm_chain.chain --input "..." --debug

  # 记录纠正
  python -m src.llm_chain.chain --correct --wrong "太正式了" --right "TA 会说随便" --scene "被催决定"
        """,
    )
    parser.add_argument("--input", "-i", type=str, default=None, help="单次问答输入")
    parser.add_argument("--chat", "-c", action="store_true", help="进入多轮聊天模式")
    parser.add_argument("--model", type=str, default=_DEFAULT_MODEL,
                        help=f"通义千问模型（默认：{_DEFAULT_MODEL}）")
    parser.add_argument("--top-k", type=int, default=_DEFAULT_TOP_K,
                        help=f"RAG 检索条目数（默认：{_DEFAULT_TOP_K}）")
    parser.add_argument("--debug", action="store_true", help="输出 Prompt 预览（单次问答有效）")
    parser.add_argument("--correct", action="store_true", help="记录一条行为纠正（不调用 LLM）")
    parser.add_argument("--wrong", type=str, default="", help="不应该有的行为")
    parser.add_argument("--right", type=str, default="", help="应该如何表现")
    parser.add_argument("--scene", type=str, default="通用场景", help="场景标签")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        if args.correct:
            if not args.wrong or not args.right:
                print("错误：--correct 需要同时提供 --wrong 和 --right 参数", file=sys.stderr)
                sys.exit(1)
            corrections = load_corrections()
            import datetime
            max_id = max(
                (int(c.get("id", "c0").lstrip("c") or 0) for c in corrections),
                default=0,
            )
            corrections.append({
                "id": f"c{str(max_id + 1).zfill(3)}",
                "scene": args.scene,
                "wrong": args.wrong,
                "correct": args.right,
                "timestamp": datetime.date.today().isoformat(),
            })
            save_corrections(corrections)
            print(f"已记录纠正：[{args.scene}] 不应「{args.wrong}」，应「{args.right}」")
            return

        chain = DigitalCloneChain(model=args.model, top_k=args.top_k)

        if args.chat:
            # 多轮聊天模式
            chain.chat_loop()
            return

        if not args.input:
            # 未传任何参数时，默认进入聊天模式
            chain.chat_loop()
            return

        # 单次问答模式
        if args.debug:
            output, preview = chain.run_with_preview(args.input)
            print(preview)
            print()
        else:
            output = chain.run(args.input)
        print(output.to_display())

    except ValueError as e:
        print(f"配置错误：{e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"运行错误：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
