"""
版本管理模块
对 data/mock_history.json 和 persona.yaml 等重要文件提供
备份（backup）、列出（list）、回滚（rollback）、清理（cleanup）能力。

备份存储位置：data/versions/{YYYYMMDD_HHMMSS}/{filename}
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).parent.parent.parent
_VERSIONS_DIR = _PROJECT_ROOT / "data" / "versions"

_MANAGED_FILES = [
    _PROJECT_ROOT / "data" / "mock_history.json",
    _PROJECT_ROOT / "data" / "corrections.json",
    _PROJECT_ROOT / "persona.yaml",
]


# ------------------------------------------------------------------ #
# 核心操作
# ------------------------------------------------------------------ #

def backup(
    file_path: str | Path | None = None,
    label: str | None = None,
) -> Path:
    """
    备份指定文件（或所有托管文件）到版本目录。

    Args:
        file_path: 要备份的文件路径。为 None 时备份所有托管文件。
        label: 可选备注标签，附加在时间戳目录名后（如 "before_import"）

    Returns:
        本次备份的版本目录路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dir_name = f"{timestamp}_{label}" if label else timestamp
    version_dir = _VERSIONS_DIR / dir_name
    version_dir.mkdir(parents=True, exist_ok=True)

    targets = [Path(file_path)] if file_path else _MANAGED_FILES
    backed_up = []
    for src in targets:
        if src.exists():
            dst = version_dir / src.name
            shutil.copy2(src, dst)
            backed_up.append(src.name)

    meta = {
        "timestamp": timestamp,
        "label": label or "",
        "files": backed_up,
    }
    with open(version_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[VersionManager] 已备份 {len(backed_up)} 个文件 → {version_dir.name}")
    return version_dir


def list_versions() -> list[dict[str, Any]]:
    """
    列出所有版本备份，按时间倒序排列。

    Returns:
        每个版本的 meta 信息列表
    """
    if not _VERSIONS_DIR.exists():
        return []
    versions = []
    for ver_dir in sorted(_VERSIONS_DIR.iterdir(), reverse=True):
        if not ver_dir.is_dir():
            continue
        meta_path = ver_dir / "meta.json"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        else:
            meta = {"timestamp": ver_dir.name, "label": "", "files": []}
        meta["version_dir"] = ver_dir.name
        versions.append(meta)
    return versions


def rollback(version_dir_name: str, file_name: str | None = None) -> list[str]:
    """
    回滚到指定版本。

    Args:
        version_dir_name: 版本目录名（如 "20240501_143022" 或 "20240501_143022_before_import"）
        file_name: 只回滚指定文件名（如 "mock_history.json"），为 None 时回滚全部

    Returns:
        成功回滚的文件名列表
    """
    version_dir = _VERSIONS_DIR / version_dir_name
    if not version_dir.exists():
        raise FileNotFoundError(f"版本目录不存在：{version_dir}")

    restored = []
    for src in version_dir.iterdir():
        if src.name == "meta.json":
            continue
        if file_name and src.name != file_name:
            continue
        # 确定目标路径
        dst = _find_original_path(src.name)
        if dst is None:
            print(f"[VersionManager] 跳过未知文件：{src.name}")
            continue
        shutil.copy2(src, dst)
        restored.append(src.name)
        print(f"[VersionManager] 已还原：{src.name} ← {version_dir.name}")

    return restored


def cleanup(keep_n: int = 5) -> int:
    """
    只保留最新的 keep_n 个备份，删除多余的旧版本。

    Args:
        keep_n: 保留的最新版本数量

    Returns:
        删除的版本数量
    """
    versions = list_versions()
    to_delete = versions[keep_n:]
    deleted = 0
    for ver in to_delete:
        ver_dir = _VERSIONS_DIR / ver["version_dir"]
        shutil.rmtree(ver_dir, ignore_errors=True)
        deleted += 1
        print(f"[VersionManager] 已删除旧版本：{ver['version_dir']}")
    return deleted


# ------------------------------------------------------------------ #
# 工具函数
# ------------------------------------------------------------------ #

def _find_original_path(filename: str) -> Path | None:
    """根据文件名找到项目中对应的原始路径"""
    for managed in _MANAGED_FILES:
        if managed.name == filename:
            return managed
    return None


# ------------------------------------------------------------------ #
# 命令行入口
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser(description="数字分身版本管理工具")
    sub = parser.add_subparsers(dest="action", required=True)

    # backup
    p_backup = sub.add_parser("backup", help="备份托管文件")
    p_backup.add_argument("--file", type=str, default=None, help="只备份指定文件路径（默认备份全部）")
    p_backup.add_argument("--label", type=str, default=None, help="备注标签")

    # list
    sub.add_parser("list", help="列出所有版本")

    # rollback
    p_rollback = sub.add_parser("rollback", help="回滚到指定版本")
    p_rollback.add_argument("version", type=str, help="版本目录名")
    p_rollback.add_argument("--file", type=str, default=None, help="只回滚指定文件名")

    # cleanup
    p_cleanup = sub.add_parser("cleanup", help="清理旧版本，只保留最新 N 个")
    p_cleanup.add_argument("--keep", type=int, default=5, help="保留版本数（默认 5）")

    args = parser.parse_args()

    if args.action == "backup":
        backup(file_path=args.file, label=args.label)

    elif args.action == "list":
        versions = list_versions()
        if not versions:
            print("暂无备份版本")
        else:
            print(f"共 {len(versions)} 个版本（最新在前）：")
            for v in versions:
                label_str = f" [{v['label']}]" if v.get("label") else ""
                files_str = ", ".join(v.get("files", []))
                print(f"  {v['version_dir']}{label_str}  →  {files_str}")

    elif args.action == "rollback":
        restored = rollback(args.version, file_name=args.file)
        print(f"回滚完成，共还原 {len(restored)} 个文件：{', '.join(restored)}")

    elif args.action == "cleanup":
        deleted = cleanup(keep_n=args.keep)
        print(f"清理完成，共删除 {deleted} 个旧版本")


if __name__ == "__main__":
    main()
