"""
数据清洗模块
对导入的原始记录进行去噪、去重、格式标准化处理，
输出统一格式的结构化记录列表。
"""
import hashlib
import re
from typing import Any


# 无意义的短内容过滤阈值（字符数）
MIN_RESPONSE_LENGTH = 3

# 常见系统消息/无效内容模式
_NOISE_PATTERNS = [
    r"^\[.*?\]$",           # 纯系统标签，如 [图片] [语音] [视频]
    r"^https?://\S+$",      # 纯链接
    r"^\d{4}-\d{2}-\d{2}$", # 纯日期
    r"^[\s\-_=*#]+$",       # 纯分隔符
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS))


def clean_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    对记录列表执行完整清洗流程：
    1. 过滤无效记录（缺少必要字段、内容太短、系统消息）
    2. 文本标准化（去除多余空白、统一标点）
    3. 基于内容哈希去重

    Returns:
        清洗后的记录列表
    """
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []

    for record in records:
        record = _normalize_fields(record)

        my_response = record.get("my_response", "")
        context = record.get("context", "")

        # 过滤无效内容
        if not my_response or len(my_response) < MIN_RESPONSE_LENGTH:
            continue
        if _NOISE_RE.match(my_response):
            continue

        # 基于 (context + my_response) 哈希去重
        fingerprint = _hash(context + my_response)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)

        # 补全缺失字段
        record.setdefault("source", "unknown")
        record.setdefault("context", "未知情境")
        record.setdefault("keywords", [])
        record.setdefault("timestamp", "")
        record.setdefault("scene_type", "")

        cleaned.append(record)

    return cleaned


def _normalize_fields(record: dict[str, Any]) -> dict[str, Any]:
    """对字符串字段进行标准化处理"""
    result = dict(record)
    for field in ("my_response", "context", "scene_type"):
        val = result.get(field, "")
        if isinstance(val, str):
            result[field] = _normalize_text(val)
    return result


def _normalize_text(text: str) -> str:
    """去除多余空白、统一换行"""
    text = text.strip()
    # 合并多个连续空白为单个空格（保留换行）
    text = re.sub(r"[ \t]+", " ", text)
    # 合并超过两个连续换行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def auto_extract_keywords(my_response: str, context: str = "") -> list[str]:
    """
    简单关键词提取：基于词频统计提取名词性词汇。
    此为轻量版，不依赖 jieba，后续可替换为更好的分词工具。
    """
    combined = context + " " + my_response
    # 提取所有 2-4 字的词（简单启发式）
    candidates = re.findall(r"[\u4e00-\u9fff]{2,4}", combined)
    # 去重并取前 5 个
    seen: set[str] = set()
    keywords: list[str] = []
    for word in candidates:
        if word not in seen:
            seen.add(word)
            keywords.append(word)
        if len(keywords) >= 5:
            break
    return keywords
