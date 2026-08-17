#!/usr/bin/env python3
"""同名/别名归并分析：找出 characters 表中可疑的重复与可归并别名。

用法:
  .venv/bin/python scripts/merge_characters.py --report      # 只出报告
  .venv/bin/python scripts/merge_characters.py --apply       # 应用规则归并

规则：
  1. 别名 = 他人标准名 或 标准名 = 他人别名 → 疑似同一人（报告）
  2. 含"之妻/之夫/之母/之父/之子/之女/嫡妻/长子"等称呼 → 建议并入主人物（报告+apply 时并入 aliases 并删除独立行）
  3. 姓氏+称谓型（如 X 家的、X 家的媳妇）→ 报告
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.models import Character

REL_SUFFIX = ("之妻", "之夫", "之母", "之父", "之子", "之女", "嫡妻", "之祖", "之孙", "之叔", "之兄", "之弟", "之姐", "之妹")


def report(db) -> list[str]:
    chars = db.query(Character).order_by(Character.name).all()
    by_name = {c.name: c for c in chars}
    lines: list[str] = []

    # 1. 别名互相撞名
    for c in chars:
        for a in c.aliases or []:
            if a in by_name and a != c.name:
                other = by_name[a]
                lines.append(
                    f"[撞名] {c.name}(id={c.id}) 的别名 '{a}' 同时是独立人物 {other.name}(id={other.id})"
                )

    # 2. 亲属称谓型（建议并入主人物）
    for c in chars:
        for suf in REL_SUFFIX:
            if c.name.endswith(suf):
                base = c.name[: -len(suf)]
                if base in by_name:
                    lines.append(
                        f"[并入] {c.name}(id={c.id}) 可并入 {base}(id={by_name[base].id}) 的别名"
                    )
                break
    return lines


def apply(db) -> int:
    """把亲属称谓型独立人物并入主人物别名，删除独立行。返回处理数。"""
    chars = db.query(Character).order_by(Character.name).all()
    by_name = {c.name: c for c in chars}
    merged = 0
    for c in chars:
        for suf in REL_SUFFIX:
            if c.name.endswith(suf):
                base = c.name[: -len(suf)]
                if base in by_name and by_name[base].id != c.id:
                    main = by_name[base]
                    aliases = list(main.aliases or [])
                    if c.name not in aliases:
                        aliases.append(c.name)
                    main.aliases = aliases
                    db.delete(c)
                    merged += 1
                break
    db.commit()
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="应用规则归并")
    ap.add_argument("--db", default="data/db/stone.db")
    args = ap.parse_args()

    db = make_session(args.db)
    if args.apply:
        n = apply(db)
        print(f"归并完成：{n} 条亲属称谓型人物并入主人物")
    else:
        lines = report(db)
        if not lines:
            print("未发现可疑项")
        else:
            print(f"发现 {len(lines)} 条：")
            for l in lines:
                print(" ", l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
