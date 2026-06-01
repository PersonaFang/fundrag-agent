# backend/cache_cleaner.py
"""
缓存清理工具：清除含脏值（阿富汗/嘲笑等）的缓存文件
在启动时自动调用，或手动执行
"""

import os
import glob

DIRTY_CACHE_TOKENS = [
    "阿富汗", "嘲笑", "推理结论", "修正结论", "阿尔法调整",
    "三人经理", "显着性",
]
CACHE_DIR = "cache"


def scan_and_clean_cache(cache_dir: str = CACHE_DIR, dry_run: bool = False) -> list[str]:
    """
    扫描缓存文件，删除含脏值的文件。
    返回被删除（或检测到的）文件列表。
    """
    deleted = []
    if not os.path.exists(cache_dir):
        return deleted

    pattern = os.path.join(cache_dir, "**", "*.json")
    files = glob.glob(pattern, recursive=True)

    for filepath in files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            dirty = [t for t in DIRTY_CACHE_TOKENS if t in content]
            if dirty:
                print(f"🗑️  脏缓存：{filepath}（含：{dirty}）")
                if not dry_run:
                    os.remove(filepath)
                    deleted.append(filepath)
                else:
                    deleted.append(filepath)
        except Exception as e:
            print(f"⚠️  无法读取 {filepath}: {e}")

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}清理完成，{'发现' if dry_run else '删除'} {len(deleted)} 个脏缓存文件")
    return deleted


def auto_clean_on_startup():
    """在 graph.py 或 app.py 启动时调用"""
    if os.path.exists(CACHE_DIR):
        deleted = scan_and_clean_cache(CACHE_DIR)
        if deleted:
            print(f"✅ 自动清理了 {len(deleted)} 个含脏值的缓存文件")


if __name__ == "__main__":
    scan_and_clean_cache(dry_run=False)
