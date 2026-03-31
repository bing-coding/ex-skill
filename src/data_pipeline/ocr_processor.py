"""
OCR 截图识别模块
调用通义千问 qwen-vl-max 识别聊天截图、日记 App 截图等图片，
提取属于"我"的发言内容，输出结构化 JSON 供后续流程使用。
"""
import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import dashscope
from dashscope import MultiModalConversation


SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

_OCR_SYSTEM_PROMPT = """你是一个专业的截图内容提取工具。
你的任务是从聊天记录截图中，识别并提取"对方（左侧气泡）"的发言内容，用于还原对方的说话风格和情感模式。

规则：
1. 如果是聊天截图（微信、飞书等），只提取左侧气泡（即对方发送）的内容，忽略右侧（用户本人）的消息
2. 如果是日记/备忘录 App 截图（没有气泡区分），提取全部文字内容
3. 对每段内容，推断其所在的对话情境（如"被询问意见""分享心情""争吵后安慰"等）
4. 输出必须是合法的 JSON 数组，不要包含其他文字

输出格式：
[
  {
    "timestamp": "图片中出现的时间（若无则留空字符串）",
    "context": "简短描述这段内容所处的情境（15字以内）",
    "my_response": "对方的原文内容（左侧气泡文字）"
  }
]"""


def image_to_base64(image_path: str | Path) -> str:
    """将图片文件转换为 base64 编码字符串"""
    path = Path(image_path)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_image_mime_type(image_path: str | Path) -> str:
    """根据文件扩展名返回 MIME 类型"""
    suffix = Path(image_path).suffix.lower()
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    return mapping.get(suffix, "image/jpeg")


def process_image(image_path: str | Path, api_key: str | None = None) -> list[dict[str, Any]]:
    """
    对单张图片调用 qwen-vl-max 进行 OCR 识别。
    返回结构化的记录列表，每条包含 timestamp / context / my_response。

    Args:
        image_path: 图片文件路径
        api_key: DashScope API Key，为空时从环境变量读取

    Returns:
        解析后的记录列表，失败时返回空列表
    """
    if api_key:
        dashscope.api_key = api_key
    elif not dashscope.api_key:
        dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY", "")

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"图片文件不存在：{path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的图片格式：{path.suffix}")

    # 将图片转为 base64 data URI
    b64 = image_to_base64(path)
    mime = get_image_mime_type(path)
    data_uri = f"data:{mime};base64,{b64}"

    messages = [
        {
            "role": "user",
            "content": [
                {"image": data_uri},
                {"text": "请按照系统指令提取图片中属于我本人的内容，输出 JSON 数组。"},
            ],
        }
    ]

    response = MultiModalConversation.call(
        model="qwen-vl-max",
        messages=messages,
        system_message=_OCR_SYSTEM_PROMPT,
    )

    if response.status_code != 200:
        print(f"[OCR] API 调用失败：{response.code} - {response.message}")
        return []

    raw_text: str = response.output.choices[0].message.content[0].get("text", "")
    return _parse_ocr_output(raw_text, source_file=str(path))


def _parse_ocr_output(raw_text: str, source_file: str = "") -> list[dict[str, Any]]:
    """解析 LLM 返回的 JSON 文本，容错处理"""
    # 尝试直接解析
    try:
        records = json.loads(raw_text)
        if isinstance(records, list):
            return _normalize_records(records, source_file)
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 数组
    match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if match:
        try:
            records = json.loads(match.group())
            if isinstance(records, list):
                return _normalize_records(records, source_file)
        except json.JSONDecodeError:
            pass

    print(f"[OCR] 无法解析 LLM 输出，原文：{raw_text[:200]}")
    return []


def _normalize_records(records: list[Any], source_file: str) -> list[dict[str, Any]]:
    """统一记录格式，补充来源字段"""
    normalized = []
    for r in records:
        if not isinstance(r, dict):
            continue
        my_response = r.get("my_response", "").strip()
        if not my_response:
            continue
        normalized.append({
            "source": "image_ocr",
            "source_file": Path(source_file).name,
            "timestamp": r.get("timestamp", ""),
            "context": r.get("context", "截图内容"),
            "my_response": my_response,
            "keywords": [],
        })
    return normalized


def process_directory(
    directory: str | Path,
    api_key: str | None = None,
    recursive: bool = False,
) -> list[dict[str, Any]]:
    """
    批量处理目录下所有支持的图片文件。

    Args:
        directory: 目录路径
        api_key: DashScope API Key
        recursive: 是否递归处理子目录

    Returns:
        所有图片识别结果合并后的记录列表
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise NotADirectoryError(f"不是有效目录：{directory}")

    pattern = "**/*" if recursive else "*"
    all_records: list[dict[str, Any]] = []

    for file_path in dir_path.glob(pattern):
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        print(f"[OCR] 正在处理：{file_path.name}")
        try:
            records = process_image(file_path, api_key)
            all_records.extend(records)
            print(f"[OCR] 识别到 {len(records)} 条记录")
        except Exception as e:
            print(f"[OCR] 处理失败 {file_path.name}：{e}")

    return all_records
