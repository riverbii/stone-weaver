#!/usr/bin/env python3
"""数据库备份/恢复工具（事故预防）。

用法:
  .venv/bin/python scripts/db_backup.py                # 备份到 data/db/backups/stone-<时间戳>.db
  .venv/bin/python scripts/db_backup.py --restore <文件>  # 从备份恢复
  .venv/bin/python scripts/db_backup.py --list          # 列出备份
"""

from __future__ import annotations

import argparse
import sqlite3
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "db" / "stone.db"
BACKUP_DIR = ROOT / "data" / "db" / "backups"


def backup(db: Path = DB) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"stone-{time.strftime('%Y%m%d-%H%M%S')}.db"
    # 用 sqlite backup API（一致性快照，比文件复制安全）
    src = sqlite3.connect(str(db))
    dst = sqlite3.connect(str(dest))
    src.backup(dst)
    dst.close()
    src.close()
    print(f"✅ 备份完成: {dest}（{dest.stat().st_size/1024/1024:.1f} MB）")
    return dest


def restore(path: Path, db: Path = DB) -> None:
    if not path.exists():
        print(f"❌ 备份不存在: {path}")
        sys.exit(1)
    # 先备份当前（防误操作）
    backup(db)
    shutil.copy2(str(path), str(db))
    print(f"✅ 已从 {path} 恢复 -> {db}")


def list_backups() -> None:
    if not BACKUP_DIR.exists():
        print("无备份")
        return
    for p in sorted(BACKUP_DIR.glob("*.db"), reverse=True):
        size = p.stat().st_size / 1024 / 1024
        print(f"  {p.name}  ({size:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", type=Path, default=None)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        list_backups()
    elif args.restore:
        restore(args.restore)
    else:
        backup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
