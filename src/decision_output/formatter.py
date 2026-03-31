"""
输出格式化模块
解析 LLM 返回的文本，提取两个结构化部分：
  - Part 1：前任/自身的直接回应（「X 的回应」或「我的决策」）
  - Part 2：行为分析复盘（「为什么 TA 会这样说」或「决策复盘」）

同时兼容「数字分身」和「前任.skill」两种输出格式。
"""
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DecisionOutput:
    """结构化输出：第一人称回应 + 旁观者分析"""
    decision: str            # 直接回应部分
    retrospective: str       # 行为/情绪分析部分
    raw_text: str = ""       # LLM 原始返回文本
    decision_label: str = "回应"       # 解析到的标签名（用于还原显示）
    retro_label: str = "行为分析"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_display(self) -> str:
        """格式化为用户可读的完整输出"""
        return (
            f"【{self.decision_label}】\n{self.decision.strip()}\n\n"
            f"【{self.retro_label}】\n{self.retrospective.strip()}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "retrospective": self.retrospective,
            "raw_text": self.raw_text,
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        return self.to_display()


# 匹配第一部分：「X 的回应」或「我的决策」
_DECISION_PATTERNS = [
    (r"【(.+?的回应)】\s*(.*?)(?=【|$)", 1, 2),       # 前任.skill 格式
    (r"【(我的决策)】\s*(.*?)(?=【决策复盘】|$)", 1, 2),  # 数字分身格式
    (r"我的决策[：:]\s*(.*?)(?=决策复盘|$)", None, 1),
    (r"\[我的决策\]\s*(.*?)(?=\[决策复盘\]|$)", None, 1),
]
# 匹配第二部分：「为什么 TA 会这样说」或「决策复盘」
_RETROSPECTIVE_PATTERNS = [
    (r"【(为什么.+?)】\s*(.*?)$", 1, 2),              # 前任.skill 格式
    (r"【(决策复盘)】\s*(.*?)$", 1, 2),               # 数字分身格式
    (r"决策复盘[：:]\s*(.*?)$", None, 1),
    (r"\[决策复盘\]\s*(.*?)$", None, 1),
]


def parse_output(raw_text: str, user_input: str = "") -> DecisionOutput:
    """
    解析 LLM 输出文本，提取两个部分。
    同时兼容「前任.skill」格式（X 的回应 / 为什么 TA 会这样说）
    和「数字分身」格式（我的决策 / 决策复盘）。
    当 LLM 未按格式输出时，使用降级策略处理。

    Args:
        raw_text: LLM 返回的原始文本
        user_input: 用户的原始输入（用于降级处理时的 metadata）

    Returns:
        DecisionOutput 对象
    """
    text = raw_text.strip()

    decision, decision_label = _extract_section(text, _DECISION_PATTERNS)
    retrospective, retro_label = _extract_section(text, _RETROSPECTIVE_PATTERNS)

    # 降级：如果完全没有识别到格式，把全文作为 decision，retrospective 留空提示
    if not decision and not retrospective:
        decision, retrospective = _fallback_split(text)

    return DecisionOutput(
        decision=decision.strip(),
        retrospective=retrospective.strip(),
        raw_text=raw_text,
        decision_label=decision_label or "回应",
        retro_label=retro_label or "行为分析",
        metadata={"user_input": user_input},
    )


def _extract_section(
    text: str, patterns: list[tuple]
) -> tuple[str, str]:
    """
    尝试多个正则模式，返回 (匹配内容, 标签名) 元组。
    每个 pattern 元组格式：(regex, label_group_idx, content_group_idx)
    label_group_idx 为 None 时用固定标签。
    """
    for pattern_tuple in patterns:
        regex, label_idx, content_idx = pattern_tuple
        match = re.search(regex, text, re.DOTALL | re.IGNORECASE)
        if match:
            label = match.group(label_idx).strip() if label_idx else ""
            content = match.group(content_idx).strip()
            if content:
                return content, label
    return "", ""


def _fallback_split(text: str) -> tuple[str, str]:
    """
    降级处理：当 LLM 未按格式输出时，
    尝试将文本按段落一分为二。
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if len(paragraphs) >= 2:
        mid = len(paragraphs) // 2
        decision = "\n\n".join(paragraphs[:mid])
        retrospective = "\n\n".join(paragraphs[mid:])
    else:
        decision = text
        retrospective = "（未能解析出标准的决策复盘结构）"
    return decision, retrospective


def format_stream_chunk(chunk: str) -> str:
    """
    流式输出时，对每个 chunk 进行轻量格式处理。
    主要用于在流式场景下直接透传，不做结构化解析。
    """
    return chunk
