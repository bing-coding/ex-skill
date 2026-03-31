
本项目深受[colleague-skill](https://github.com/titanwings/colleague-skill)的启发，因此做了这个前任.skill,欢迎试用并提bug~

# 前任.skill

> 克隆你的前任。

## 两种使用方式

| | Claude Code / OpenClaw 版 | 本地 Python 版 |
|--|--|--|
| **大模型** | Claude（平台自带，零额外费用） | 通义千问 API（按 token 付费） |
| **配置** | 无需 API Key | 需要 DASHSCOPE_API_KEY |
| **启动** | 平台内输入 `/ex-partner` | `python -m src.llm_chain.chain --chat` |
| **聊天记忆** | 跨会话，自动保存 | 跨会话，自动保存 |
| **适合** | 日常使用，零成本 | 本地独立运行、二次开发 |

---

## 这是什么？

你曾经无数次猜测：**TA 当时为什么那样说？如果我当时那样做，TA 会怎么反应？**

这个 Skill 摄取你们的聊天记录和你对 TA 性格的主观描述，构建一个尽量贴近真实的前任语言模型。它会：

- 用 **TA 惯用的语气和句式**回复你的问题
- 从 **性格和关系背景**出发，分析 TA 为什么会这样说
- 在没有足够依据时，**诚实承认不确定**，而不是胡编乱造

---

## 快速开始

### 方式一：Claude Code / OpenClaw（推荐，零 API 成本）

```bash
# Claude Code：安装到全局（所有项目可用）
git clone <本仓库> ~/.claude/skills/ex-partner

# OpenClaw：
git clone <本仓库> ~/.openclaw/workspace/skills/ex-partner
```

安装后在 Claude Code 中输入 `/ex-partner` 即可触发，Claude 本身就是大模型，无需任何 API Key。

---

### 方式二：本地 Python 独立运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key（通义千问）

```bash
# Windows PowerShell
$env:DASHSCOPE_API_KEY = "your_api_key_here"

# macOS/Linux
export DASHSCOPE_API_KEY="your_api_key_here"
```

在 [阿里云百炼平台](https://dashscope.aliyun.com/) 申请 API Key，新用户有免费额度。

### 3. 描述前任（`persona.yaml`）

打开 `persona.yaml`，填入你记忆中的前任：

```yaml
name: "小A"
role: "设计师"
user_name: "你自己的名字"
relationship_context: "恋爱两年，异地，因为未来规划不同分手"

personality:
  - "感性、直觉驱动，做决定靠感受多于逻辑"
  - "生气时不会爆发，会沉默冷处理"
  # 越具体越好，写你真实记忆里的 TA
```

### 4. 喂入聊天记录（`data/raw/`）

将以下数据放入 `data/raw/`：

- **微信导出 txt**：微信电脑端 → 备份与迁移 → 导出聊天记录
- **聊天截图**：OCR 自动提取左侧气泡（前任说的话）
- **自制 JSON/CSV**：按格式整理的对话片段

```bash
# 导入前任的发言（指定前任在微信里的昵称）
python -m src.data_pipeline.importer --my-name "前任的微信昵称"
```

### 5. 开始对话

```bash
# 聊天模式（推荐）—— 自动加载历史记忆，跨会话连续
python -m src.llm_chain.chain --chat

# 单次问答（无上下文）
python -m src.llm_chain.chain --input "TA 当时为什么突然就不回消息了"
```

聊天模式启动时会自动加载上次的对话记忆，TA 记得你们之前聊过的内容。

**查看历史记忆统计：**
```bash
python -m src.tools.history_manager --action list
```

---

## 对话示例

**你**：TA 当时说的"看吧"是什么意思？

```
【小A 的回应】
就是不确定啊，我那时候真的不知道自己想不想去。
你总是要我给一个确定的答案，但我就是不知道嘛。

【为什么 TA 会这样说】
"看吧"是小A处理不想正面回答时的惯用语。
TA倾向于用模糊回应避免冲突，同时保留自己的灵活性。
当感到被催促时，这种回应会更频繁。
```

---

## 纠错：让它更像 TA

如果某次回复不对味，可以告诉它：

```bash
python -m src.llm_chain.chain --correct \
  --wrong "这样说太正式了，TA 不会这样" \
  --right "TA 应该会说'你想太多了'" \
  --scene "对方过度解读"
```

纠正记录会被存入 `data/corrections.json`，下次对话时自动参考。

---

## 目录结构

```
前任.skill/
├── persona.yaml          # 前任的性格描述（你来填）
├── data/
│   ├── raw/              # 原始聊天记录、截图放这里
│   ├── mock_history.json # 处理后的语料库（自动生成）
│   └── corrections.json  # 纠错记录
├── src/
│   ├── data_pipeline/    # 数据导入 + OCR
│   ├── memory/           # 静态记忆 + RAG 检索
│   ├── persona_engine/   # Prompt 拼装
│   ├── decision_output/  # 输出格式解析
│   ├── llm_chain/        # 主对话链路
│   └── tools/            # 版本管理等工具
└── tests/                # 测试用例
```

---

## API 费用参考

| 操作 | 模型 | 估算费用 |
|------|------|---------|
| 单次对话 | qwen-max | ~0.02-0.05 元 |
| 图片 OCR（每张截图） | qwen-vl-max | ~0.05-0.1 元 |
| 日常使用 100 次/月 | 混合 | ~2-5 元 |

---

> **关于这个工具的使用**：它是一面镜子，帮你理解那段关系里 TA 的视角，而不是制造幻觉。如果某个回复感觉"太好了""完全不像 TA"，那大概率是喂入的数据不够，或者 persona.yaml 需要更新。
