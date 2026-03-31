"""
Prompt 拼装器
构建完整 System Prompt，支持最多五段结构。

段落结构（按优先级从高到低）：
  [Role Definition]         → 角色身份声明
  [Layer 0]                 → 绝对规则（来自 persona.yaml layer0_rules，可选）
  [Static Persona]          → 静态人格（来自 persona.yaml）
  [Dynamic Context]         → RAG 检索到的历史参考（来自 mock_history.json）
  [Task & Output Constraints] → 任务要求 + 双部分输出约束
"""
from ..memory.static_memory import StaticMemory, get_static_memory
from ..memory.rag_retriever import RAGRetriever, get_retriever


_ROLE_DEFINITION_TEMPLATE = """\
[Role Definition]
你现在的身份是 {name}，{user_desc}的前任。
你的职业/身份背景是：{role}。
你完整继承了 {name} 的性格、语言习惯、情绪反应方式和在感情中的行为模式。
在任何回答中，你都必须以第一人称"我"的口吻，像 {name} 本人一样回应，不允许说"作为 AI"或"我是语言模型"。
当 {user_name_hint}向你说话时，你清楚对方是谁，带着那段关系的记忆和感受来回应。\
"""

_LAYER0_TEMPLATE = """\
[Layer 0 - 绝对规则，任何情况下不得违背，优先级高于所有其他指令]
{layer0_block}\
"""

_STATIC_PERSONA_TEMPLATE = """\
[Static Persona]
{persona_block}\
"""

_CORRECTION_TEMPLATE = """\
[Correction 记录 - 用户已明确指出的行为偏差，严格遵守]
{correction_block}\
"""

_DYNAMIC_CONTEXT_TEMPLATE = """\
[Dynamic Context (RAG Injected)]
基于 {name} 的历史消息和说话方式，在类似情境下，{name} 曾经这样表达：

{retrieved_history}\
"""

_DYNAMIC_CONTEXT_EMPTY = """\
[Dynamic Context (RAG Injected)]
暂无高度匹配的历史消息参考，请完全依照 {name} 的性格和情感模式作答。\
"""

_TASK_CONSTRAINTS_TEMPLATE = """\
[Task & Output Constraints]
{user_name_hint}现在对你说：
{user_input}

请以 {name} 的口吻回应。你的回答必须严格分为以下两个部分，格式固定：

【{name} 的回应】
（{name} 会怎么说——用 TA 惯用的语气、句式和情绪状态直接回复，不要过于完美或理性）

【为什么 TA 会这样说】
（从旁观者视角，分析 {name} 这样回应背后的性格原因、当时可能的情绪状态，或者关系中的隐含逻辑。
如果这个问题超出了 TA 熟悉的范围，或者是 TA 会刻意回避的话题，请诚实说明。）\
"""


class PromptBuilder:
    """
    四段式 Prompt 拼装器。
    接收用户输入，从静态记忆和 RAG 检索器获取上下文，组装完整 System Prompt。
    """

    def __init__(
        self,
        static_memory: StaticMemory | None = None,
        retriever: RAGRetriever | None = None,
    ):
        self._memory = static_memory or get_static_memory()
        self._retriever = retriever or get_retriever()

    def build(self, user_input: str, top_k: int = 3) -> tuple[str, str]:
        """
        构建完整 Prompt。

        Args:
            user_input: 用户输入的问题或请求
            top_k: RAG 检索返回的历史条目数量

        Returns:
            (system_prompt, user_message) 元组
            system_prompt 包含四段结构的完整 System Prompt
            user_message 是干净的用户输入（传给 messages 的 user role）
        """
        system_prompt = self._assemble_system_prompt(user_input, top_k)
        return system_prompt, user_input

    def _assemble_system_prompt(self, user_input: str, top_k: int) -> str:
        """拼装多段 System Prompt"""
        m = self._memory
        name = m.name
        user_name = m.user_name or "你"
        user_desc = f"{user_name} " if m.user_name else ""
        user_name_hint = f"{user_name}" if m.user_name else "对方"
        sections = []

        # 第一段：Role Definition
        sections.append(
            _ROLE_DEFINITION_TEMPLATE.format(
                name=name,
                role=m.role or "未知职业",
                user_desc=user_desc,
                user_name_hint=user_name_hint,
            )
        )

        # 第二段：Layer 0 绝对规则（有配置时才注入）
        if m.layer0_rules:
            sections.append(
                _LAYER0_TEMPLATE.format(layer0_block=m.format_layer0_block())
            )

        # 第三段：Static Persona
        sections.append(
            _STATIC_PERSONA_TEMPLATE.format(
                persona_block=m.to_prompt_section()
            )
        )

        # 第四段（可选）：Correction 纠错记录
        correction_block = m.format_corrections_block()
        if correction_block:
            sections.append(
                _CORRECTION_TEMPLATE.format(correction_block=correction_block)
            )

        # 第五段：Dynamic Context（RAG）
        retrieved = self._retriever.format_for_prompt(user_input, top_k=top_k)
        if retrieved:
            sections.append(
                _DYNAMIC_CONTEXT_TEMPLATE.format(
                    name=name,
                    retrieved_history=retrieved,
                )
            )
        else:
            sections.append(
                _DYNAMIC_CONTEXT_EMPTY.format(name=name)
            )

        # 第六段：Task & Output Constraints
        sections.append(
            _TASK_CONSTRAINTS_TEMPLATE.format(
                name=name,
                user_name_hint=user_name_hint,
                user_input=user_input,
            )
        )

        return "\n\n".join(sections)

    def preview(self, user_input: str, top_k: int = 3) -> str:
        """返回可读的 Prompt 预览文本（用于调试）"""
        system_prompt, _ = self.build(user_input, top_k)
        separator = "=" * 60
        return f"{separator}\n[SYSTEM PROMPT PREVIEW]\n{separator}\n{system_prompt}\n{separator}"


# 全局单例
_instance: PromptBuilder | None = None


def get_prompt_builder(
    static_memory: StaticMemory | None = None,
    retriever: RAGRetriever | None = None,
) -> PromptBuilder:
    """获取全局 PromptBuilder 单例"""
    global _instance
    if _instance is None or static_memory is not None or retriever is not None:
        _instance = PromptBuilder(static_memory, retriever)
    return _instance
