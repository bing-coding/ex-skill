"""
数据导入模块
支持多种格式的原始数据导入：txt / md / json / csv / png / jpg
对图片格式自动调用 OCR 模块，统一输出结构化记录列表写入 mock_history.json。

注意：本模块面向「前任.skill」，my_name 参数应传入前任的昵称（即要提取的目标人物），
而非用户自己的名字。
"""
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .cleaner import clean_records, auto_extract_keywords
from .ocr_processor import process_image, SUPPORTED_EXTENSIONS as IMAGE_EXTENSIONS
from ..tools.version_manager import backup as _version_backup


_PROJECT_ROOT = Path(__file__).parent.parent.parent
_RAW_DIR = _PROJECT_ROOT / "data" / "raw"
_CLEANED_DIR = _PROJECT_ROOT / "data" / "cleaned"
_OUTPUT_PATH = _PROJECT_ROOT / "data" / "mock_history.json"

TEXT_EXTENSIONS = {".txt", ".md"}
JSON_EXTENSIONS = {".json"}
CSV_EXTENSIONS = {".csv"}


# ------------------------------------------------------------------ #
# 主入口
# ------------------------------------------------------------------ #

def run_import(
    raw_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    api_key: str | None = None,
    merge: bool = True,
    my_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    扫描 raw_dir 目录下所有支持的文件，导入并清洗后写入 output_path。

    Args:
        raw_dir: 原始数据目录，默认为 data/raw/
        output_path: 输出 JSON 路径，默认为 data/mock_history.json
        api_key: DashScope API Key（图片 OCR 使用）
        merge: 是否与现有数据合并（True），还是覆盖（False）
        my_name: 微信聊天记录中前任的昵称/备注，用于过滤只保留前任的发言。
                 为 None 时保留全部消息（需手动清理）。

    Returns:
        清洗后的所有记录列表
    """
    raw_path = Path(raw_dir) if raw_dir else _RAW_DIR
    out_path = Path(output_path) if output_path else _OUTPUT_PATH

    if not raw_path.exists():
        print(f"[Importer] raw 目录不存在，跳过：{raw_path}")
        return []

    all_records: list[dict[str, Any]] = []

    for file_path in sorted(raw_path.iterdir()):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        print(f"[Importer] 处理文件：{file_path.name}")

        if suffix in TEXT_EXTENSIONS:
            records = import_text_file(file_path, my_name=my_name)
        elif suffix in JSON_EXTENSIONS:
            records = import_json_file(file_path)
        elif suffix in CSV_EXTENSIONS:
            records = import_csv_file(file_path)
        elif suffix in IMAGE_EXTENSIONS:
            records = import_image_file(file_path, api_key)
        else:
            print(f"[Importer] 跳过不支持的格式：{suffix}")
            continue

        print(f"[Importer]   → 提取到 {len(records)} 条原始记录")
        all_records.extend(records)

    # 清洗
    cleaned = clean_records(all_records)
    print(f"[Importer] 清洗后共 {len(cleaned)} 条有效记录")

    # 自动补全缺失 keywords
    for r in cleaned:
        if not r.get("keywords"):
            r["keywords"] = auto_extract_keywords(
                r.get("my_response", ""), r.get("context", "")
            )

    # 分配 ID
    cleaned = _assign_ids(cleaned, out_path if merge else None)

    # 写入前自动备份现有语料（如存在）
    if out_path.exists():
        _version_backup(file_path=out_path, label="before_import")

    # 写入输出文件
    _cleaned_dir = _CLEANED_DIR
    _cleaned_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    print(f"[Importer] 已写入：{out_path}")

    return cleaned


# ------------------------------------------------------------------ #
# 各格式解析器
# ------------------------------------------------------------------ #

def import_text_file(file_path: Path, my_name: str | None = None) -> list[dict[str, Any]]:
    """
    解析 txt/md 文件。
    支持两种格式：
    1. 微信导出格式：每行 "时间  发送者\n内容"
    2. 普通文本：以空行分段，每段作为一条记录

    Args:
        file_path: 文件路径
        my_name: 微信聊天记录中本人的昵称，用于过滤只保留本人发言
    """
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # 尝试微信导出格式解析
    wechat_records = _parse_wechat_txt(content, source_file=file_path.name, my_name=my_name)
    if wechat_records:
        return wechat_records

    # 普通文本：按段落分割
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", content) if p.strip()]
    records = []
    for para in paragraphs:
        if len(para) < 5:
            continue
        records.append({
            "source": "memo" if file_path.suffix == ".md" else "txt",
            "source_file": file_path.name,
            "context": "备忘录内容",
            "my_response": para,
            "keywords": [],
            "timestamp": "",
        })
    return records


def import_json_file(file_path: Path) -> list[dict[str, Any]]:
    """解析 JSON 文件，支持列表格式和单个对象格式"""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = [data]
    else:
        return []

    # 添加来源标注
    for r in records:
        r.setdefault("source", "json")
        r.setdefault("source_file", file_path.name)
    return records


def import_csv_file(file_path: Path) -> list[dict[str, Any]]:
    """
    解析 CSV 文件。
    期望列：context, my_response（必须），source, keywords, timestamp（可选）
    """
    records = []
    with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("my_response"):
                continue
            records.append({
                "source": row.get("source", "csv"),
                "source_file": file_path.name,
                "context": row.get("context", ""),
                "my_response": row.get("my_response", ""),
                "keywords": [k.strip() for k in row.get("keywords", "").split(",") if k.strip()],
                "timestamp": row.get("timestamp", ""),
            })
    return records


def import_image_file(file_path: Path, api_key: str | None = None) -> list[dict[str, Any]]:
    """调用 OCR 模块处理图片文件"""
    key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        print(f"[Importer] 警告：未设置 DASHSCOPE_API_KEY，跳过图片 {file_path.name}")
        return []
    try:
        return process_image(file_path, api_key=key)
    except Exception as e:
        print(f"[Importer] 图片 OCR 失败 {file_path.name}：{e}")
        return []


# ------------------------------------------------------------------ #
# 工具函数
# ------------------------------------------------------------------ #

_WECHAT_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(.+)$"
)


def _parse_wechat_txt(
    content: str,
    source_file: str = "",
    my_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    解析微信电脑端导出的 txt 格式。
    格式：时间行 + 发送者行 + 内容行（可能多行），空行分隔消息块。

    Args:
        content: 文件文本内容
        source_file: 来源文件名（用于记录 metadata）
        my_name: 前任在聊天记录中的昵称。提供时只保留前任的发言；
                 为 None 时保留全部非系统消息（需用户自行筛选）。
    """
    lines = content.splitlines()
    records: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = _WECHAT_LINE_RE.match(line)
        if match:
            timestamp = match.group(1)
            sender = match.group(2).strip()
            # 收集后续内容行（直到下一个时间戳行）
            content_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if _WECHAT_LINE_RE.match(next_line.strip()):
                    break
                if next_line.strip():
                    content_lines.append(next_line.strip())
                i += 1
            msg_content = "\n".join(content_lines).strip()

            # 过滤系统消息
            if not msg_content or sender in ("系统消息", "System"):
                continue

            # 若指定了 my_name，只保留本人发言
            if my_name is not None and sender != my_name:
                continue

            records.append({
                "source": "wechat",
                "source_file": source_file,
                "timestamp": timestamp,
                "sender": sender,
                "context": "微信聊天",
                "my_response": msg_content,
                "keywords": [],
            })
        else:
            i += 1

    if len(records) <= 2:
        return []

    if my_name is None:
        print(
            "[Importer] 提示：微信记录包含双方消息，建议传入 my_name 参数指定前任的昵称，只保留前任的发言。\n"
            "  示例：run_import(my_name='前任的昵称')"
        )
    return records


def _assign_ids(
    records: list[dict[str, Any]], existing_path: Path | None = None
) -> list[dict[str, Any]]:
    """分配/补全记录 ID，合并时保留已有记录的 ID"""
    existing: list[dict[str, Any]] = []
    if existing_path and existing_path.exists():
        with open(existing_path, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []

    # 已有 ID 的最大值
    max_id = 0
    for r in existing:
        try:
            max_id = max(max_id, int(r.get("id", "0")))
        except (ValueError, TypeError):
            pass

    # 合并时，现有记录优先保留
    existing_responses = {r.get("my_response", "") for r in existing}
    merged = list(existing)
    for r in records:
        if r.get("my_response", "") not in existing_responses:
            max_id += 1
            r["id"] = str(max_id).zfill(3)
            merged.append(r)

    return merged


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="前任.skill 语料导入工具")
    parser.add_argument("--raw-dir", type=str, default=None, help="原始数据目录（默认 data/raw/）")
    parser.add_argument("--my-name", type=str, default=None, help="微信聊天记录中前任的昵称，用于过滤只保留前任的发言")
    parser.add_argument("--no-merge", action="store_true", help="覆盖模式（不与现有数据合并）")
    args = parser.parse_args()

    run_import(
        raw_dir=args.raw_dir,
        merge=not args.no_merge,
        my_name=args.my_name,
    )
