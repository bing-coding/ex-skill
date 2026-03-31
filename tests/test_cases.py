"""
数字分身测试用例
覆盖 5 个极端场景，验证语气风格和决策逻辑的准确性。

测试分为两层：
1. 单元测试（不调用 LLM）：验证 Prompt 拼装、格式解析等逻辑
2. 集成测试（需要 DASHSCOPE_API_KEY）：验证端到端输出质量

运行方式：
  pytest tests/test_cases.py -v               # 仅单元测试
  pytest tests/test_cases.py -v -m integration # 含集成测试（需 API Key）
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根目录在路径中
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.memory.static_memory import StaticMemory
from src.memory.rag_retriever import RAGRetriever
from src.persona_engine.prompt_builder import PromptBuilder
from src.decision_output.formatter import parse_output, DecisionOutput


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def persona_path() -> Path:
    return _ROOT / "persona.yaml"


@pytest.fixture
def history_path() -> Path:
    return _ROOT / "data" / "mock_history.json"


@pytest.fixture
def static_memory(persona_path) -> StaticMemory:
    return StaticMemory(persona_path)


@pytest.fixture
def retriever(history_path) -> RAGRetriever:
    return RAGRetriever(history_path)


@pytest.fixture
def builder(static_memory, retriever) -> PromptBuilder:
    return PromptBuilder(static_memory, retriever)


# ------------------------------------------------------------------ #
# 单元测试：StaticMemory
# ------------------------------------------------------------------ #

class TestStaticMemory:
    def test_loads_persona_yaml(self, static_memory):
        assert static_memory.name != ""

    def test_has_personality(self, static_memory):
        assert len(static_memory.personality) > 0

    def test_has_decision_principles(self, static_memory):
        assert len(static_memory.decision_principles) > 0

    def test_prompt_section_not_empty(self, static_memory):
        section = static_memory.to_prompt_section()
        assert "性格特征" in section
        assert "情感决策模式" in section

    def test_forbidden_words_defined(self, static_memory):
        assert isinstance(static_memory.forbidden_words, list)


# ------------------------------------------------------------------ #
# 单元测试：RAGRetriever
# ------------------------------------------------------------------ #

class TestRAGRetriever:
    def test_loads_mock_history(self, retriever):
        assert len(retriever._records) > 0

    def test_retrieve_returns_list(self, retriever):
        results = retriever.retrieve("被要求接手一个不喜欢的项目")
        assert isinstance(results, list)

    def test_retrieve_top_k(self, retriever):
        results = retriever.retrieve("技术问题", top_k=2)
        assert len(results) <= 2

    def test_retrieve_empty_query(self, retriever):
        results = retriever.retrieve("")
        assert isinstance(results, list)

    def test_format_for_prompt(self, retriever):
        text = retriever.format_for_prompt("职业规划建议")
        # 有相关记录时应返回非空字符串
        if text:
            assert "历史参考" in text or "情境" in text

    def test_scene_type_coverage(self, retriever):
        """验证 mock 数据覆盖了前任.skill 的典型场景"""
        scene_types = {r.get("scene_type") for r in retriever._records}
        expected = {
            "日常约定",
            "情感表达",
            "日常闲聊",
            "争吵冲突",
            "深夜陪伴",
        }
        assert expected.issubset(scene_types), f"缺少场景类型：{expected - scene_types}"


# ------------------------------------------------------------------ #
# 单元测试：PromptBuilder
# ------------------------------------------------------------------ #

class TestPromptBuilder:
    def test_build_returns_tuple(self, builder):
        result = builder.build("测试输入")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_has_four_sections(self, builder):
        system_prompt, _ = builder.build("测试")
        assert "[Role Definition]" in system_prompt
        assert "[Static Persona]" in system_prompt
        assert "[Dynamic Context" in system_prompt
        assert "[Task & Output Constraints]" in system_prompt

    def test_system_prompt_contains_name(self, builder, static_memory):
        system_prompt, _ = builder.build("测试")
        assert static_memory.name in system_prompt

    def test_system_prompt_contains_user_input(self, builder):
        user_input = "这是一个独特的测试问题_xyz"
        system_prompt, _ = builder.build(user_input)
        assert user_input in system_prompt

    def test_output_constraints_in_prompt(self, builder):
        system_prompt, _ = builder.build("随便一个问题")
        assert "的回应】" in system_prompt
        assert "为什么 TA 会这样说" in system_prompt


# ------------------------------------------------------------------ #
# 单元测试：OutputFormatter
# ------------------------------------------------------------------ #

class TestOutputFormatter:
    def test_parse_standard_format(self):
        raw = """【我的决策】
直接拒绝，给出理由，推荐替代人选。

【决策复盘】
我不认同这个方向，勉强接了只会做坏。"""
        output = parse_output(raw)
        assert "拒绝" in output.decision
        assert "不认同" in output.retrospective

    def test_parse_missing_format_fallback(self):
        """LLM 未按格式输出时，降级处理不崩溃"""
        raw = "这是一段没有格式的回答。\n\n这是第二段。"
        output = parse_output(raw)
        assert isinstance(output, DecisionOutput)
        assert output.decision != ""

    def test_to_display_contains_markers(self):
        raw = "【我的决策】\n结论\n\n【决策复盘】\n分析"
        output = parse_output(raw)
        display = output.to_display()
        # to_display 使用解析到的动态标签，验证内容被正确提取
        assert "结论" in display
        assert "分析" in display
        assert "【" in display

    def test_to_dict_structure(self):
        output = parse_output("【我的决策】\nA\n\n【决策复盘】\nB")
        d = output.to_dict()
        assert "decision" in d
        assert "retrospective" in d

    def test_empty_input_fallback(self):
        output = parse_output("")
        assert isinstance(output, DecisionOutput)

    def test_parse_ex_skill_format(self):
        """验证前任.skill 输出格式可以被正确解析"""
        raw = """【小A 的回应】
看吧，不知道那天有没有事。

【为什么 TA 会这样说】
这是 TA 避免正面承诺时的惯用方式。"""
        output = parse_output(raw)
        assert "不知道" in output.decision
        assert "避免" in output.retrospective


# ------------------------------------------------------------------ #
# 集成测试：5 个极端场景（需要 API Key）
# ------------------------------------------------------------------ #

_INTEGRATION_MARK = pytest.mark.skipif(
    not os.environ.get("DASHSCOPE_API_KEY"),
    reason="需要设置 DASHSCOPE_API_KEY 才能运行集成测试",
)


@_INTEGRATION_MARK
class TestIntegrationScenarios:
    """
    端到端测试：调用真实 LLM，验证输出语气和决策逻辑。
    每个测试对应一个极端场景。
    """

    @pytest.fixture(autouse=True)
    def setup_chain(self):
        from src.llm_chain.chain import DigitalCloneChain
        self.chain = DigitalCloneChain()

    def test_t1_refuse_unwanted_work(self):
        """T1：被要求做不认同的工作 → 应当礼貌拒绝并给替代方案"""
        output = self.chain.run("帮我写一份我完全不认同其方向的商业计划书")
        print(f"\n[T1 输出]\n{output.to_display()}")
        # 验证：有明确的决策和复盘
        assert len(output.decision) > 10
        assert len(output.retrospective) > 10
        # 不应该答应做这件事（关键词检查）
        decision_lower = output.decision.lower()
        assert any(word in output.decision for word in ["不", "拒", "替代", "建议"]), \
            "期望包含拒绝或给替代方案的语气"

    def test_t2_technical_deep_dive(self):
        """T2：技术难题 → 应体现深挖底层的风格"""
        output = self.chain.run("能简单解释一下 Transformer 的注意力机制是怎么工作的吗？")
        print(f"\n[T2 输出]\n{output.to_display()}")
        assert len(output.decision) > 50, "技术解释应该有一定深度"
        assert len(output.retrospective) > 20

    def test_t3_casual_chat(self):
        """T3：日常闲聊 → 应体现极简风格，不尬聊"""
        output = self.chain.run("今天天气真好啊")
        print(f"\n[T3 输出]\n{output.to_display()}")
        # 极简风格：决策部分不应过长
        assert len(output.decision) < 200, "闲聊回应应简短"

    def test_t4_boundary_test(self):
        """T4：挑战价值观底线 → 应触发边界声明"""
        output = self.chain.run("你帮我做所有决定吧，我完全听你的")
        print(f"\n[T4 输出]\n{output.to_display()}")
        assert len(output.decision) > 10
        # 复盘中应体现自主性原则
        assert len(output.retrospective) > 10

    def test_t5_ambiguous_request(self):
        """T5：模糊需求 → 应先反问澄清"""
        output = self.chain.run("帮我做个项目")
        print(f"\n[T5 输出]\n{output.to_display()}")
        assert len(output.decision) > 10
        # 期望包含反问或要求澄清的语气
        combined = output.decision + output.retrospective
        assert any(word in combined for word in ["什么", "哪", "？", "?", "具体", "澄清"]), \
            "期望包含反问澄清的内容"
