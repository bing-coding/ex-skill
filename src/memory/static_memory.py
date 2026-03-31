"""
静态记忆模块：解析 persona.yaml 和 corrections.json，对外暴露结构化人格数据
"""
import json
import os
import yaml
from pathlib import Path
from typing import Any


_PERSONA_PATH = Path(__file__).parent.parent.parent / "persona.yaml"
_CORRECTIONS_PATH = Path(__file__).parent.parent.parent / "data" / "corrections.json"


def load_persona(path: str | Path | None = None) -> dict[str, Any]:
    """加载并解析 persona.yaml，返回原始字典"""
    target = Path(path) if path else _PERSONA_PATH
    if not target.exists():
        raise FileNotFoundError(f"persona.yaml 未找到：{target}")
    with open(target, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_corrections(path: str | Path | None = None) -> list[dict[str, Any]]:
    """加载 corrections.json，不存在时返回空列表"""
    target = Path(path) if path else _CORRECTIONS_PATH
    if not target.exists():
        return []
    with open(target, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []


def save_corrections(
    corrections: list[dict[str, Any]],
    path: str | Path | None = None,
) -> None:
    """将 corrections 写回 corrections.json"""
    target = Path(path) if path else _CORRECTIONS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(corrections, f, ensure_ascii=False, indent=2)


class StaticMemory:
    """
    静态记忆对象，封装 persona.yaml 中所有人格字段。
    在 Prompt 拼装时作为只读数据源使用。
    """

    def __init__(self, path: str | Path | None = None, corrections_path: str | Path | None = None):
        data = load_persona(path)
        self.name: str = data.get("name", "前任")
        self.role: str = data.get("role", "")
        self.user_name: str = data.get("user_name", "")
        self.relationship_context: str = data.get("relationship_context", "")
        self.layer0_rules: list[str] = data.get("layer0_rules", [])
        self.personality: list[str] = data.get("personality", [])
        self.language_preferred: list[str] = data.get("language_style", {}).get("preferred", [])
        self.language_avoided: list[str] = data.get("language_style", {}).get("avoided", [])
        self.forbidden_words: list[str] = data.get("forbidden_words", [])
        self.decision_principles: list[str] = data.get("decision_principles", [])
        self.values: list[str] = data.get("values", [])
        self.expertise_strong: list[str] = data.get("expertise", {}).get("strong", [])
        self.expertise_moderate: list[str] = data.get("expertise", {}).get("moderate", [])
        self.expertise_weak: list[str] = data.get("expertise", {}).get("weak_and_honest", [])
        self.knowledge_boundary: list[str] = data.get("knowledge_boundary", [])
        self.emotional_style: list[str] = data.get("emotional_style", [])
        self.corrections: list[dict[str, Any]] = load_corrections(corrections_path)

    def format_layer0_block(self) -> str:
        """将 Layer 0 绝对规则格式化为 Prompt 片段"""
        return "\n".join(f"- {r}" for r in self.layer0_rules)

    def format_personality_block(self) -> str:
        """将性格特征格式化为 Prompt 片段"""
        lines = [f"- {p}" for p in self.personality]
        return "\n".join(lines)

    def format_language_block(self) -> str:
        """将语言风格格式化为 Prompt 片段"""
        preferred = "\n".join(f"  - {s}" for s in self.language_preferred)
        avoided = "\n".join(f"  - {s}" for s in self.language_avoided)
        parts = []
        if preferred:
            parts.append(f"习惯用法：\n{preferred}")
        if avoided:
            parts.append(f"刻意回避：\n{avoided}")
        return "\n".join(parts)

    def format_decision_principles_block(self) -> str:
        """将决策原则格式化为 Prompt 片段"""
        lines = [f"- {p}" for p in self.decision_principles]
        return "\n".join(lines)

    def format_expertise_block(self) -> str:
        """将技能栈格式化为 Prompt 片段"""
        parts = []
        if self.expertise_strong:
            strong = "、".join(self.expertise_strong)
            parts.append(f"擅长：{strong}")
        if self.expertise_moderate:
            moderate = "、".join(self.expertise_moderate)
            parts.append(f"有一定了解（能做但非专长）：{moderate}")
        if self.expertise_weak:
            weak = "、".join(self.expertise_weak)
            parts.append(f"知识盲区（会主动承认）：{weak}")
        return "\n".join(parts)

    def format_values_block(self) -> str:
        """将核心价值观格式化为 Prompt 片段"""
        return "\n".join(f"- {v}" for v in self.values)

    def format_forbidden_words_block(self) -> str:
        """将禁用词汇格式化为 Prompt 片段"""
        if not self.forbidden_words:
            return ""
        return "、".join(self.forbidden_words)

    def format_emotional_style_block(self) -> str:
        """将情绪风格格式化为 Prompt 片段"""
        return "\n".join(f"- {e}" for e in self.emotional_style)

    def format_corrections_block(self) -> str:
        """将已记录的纠正项格式化为 Prompt 片段"""
        if not self.corrections:
            return ""
        lines = []
        for c in self.corrections:
            scene = c.get("scene", "通用场景")
            wrong = c.get("wrong", "")
            correct = c.get("correct", "")
            if wrong and correct:
                lines.append(f"- [{scene}] 不应该「{wrong}」，应该「{correct}」")
        return "\n".join(lines)

    def to_prompt_section(self) -> str:
        """输出完整的 [Static Persona] Prompt 段落"""
        sections = []
        if self.relationship_context:
            user_label = f"与 {self.user_name} 的关系背景" if self.user_name else "关系背景"
            sections.append(f"{user_label}：{self.relationship_context}")
        sections += [
            f"性格特征：\n{self.format_personality_block()}",
            f"语言风格：\n{self.format_language_block()}",
            f"情感决策模式：\n{self.format_decision_principles_block()}",
        ]
        expertise = self.format_expertise_block()
        if expertise:
            sections.append(f"兴趣与专业倾向：\n{expertise}")
        if self.values:
            sections.append(f"核心在乎的事（不可违背）：\n{self.format_values_block()}")
        forbidden = self.format_forbidden_words_block()
        if forbidden:
            sections.append(f"绝对不会说的词（从不用）：{forbidden}")
        if self.emotional_style:
            sections.append(f"情绪模式：\n{self.format_emotional_style_block()}")
        return "\n\n".join(sections)

    def __repr__(self) -> str:
        return f"<StaticMemory name={self.name!r} role={self.role!r}>"


_instance: StaticMemory | None = None


def get_static_memory(path: str | Path | None = None) -> StaticMemory:
    """获取全局单例 StaticMemory，避免重复读取文件"""
    global _instance
    if _instance is None or path is not None:
        _instance = StaticMemory(path)
    return _instance
