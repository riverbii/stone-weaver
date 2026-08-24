#!/usr/bin/env python3
"""规范化引擎回的"题曰"格式：题曰独立一行，诗句按联分行（对齐原文结构）。

原文格式（guihui_v3）：
  题曰：
  verse
  玉楼倩句爱清奇，香腕挥毫情自持。
  十首冰心谁辨真，肯将衷曲付残枝。
  verse

本脚本把引擎回的"题曰：诗一，诗二。诗三，诗四。"统一为：
  题曰：
  诗一，诗二。
  诗三，诗四。

用法:
  .venv/bin/python scripts/normalize_tiyu.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.models import GeneratedChapter


def normalize(text: str) -> str:
    """规范化题曰格式。返回 (规范化后的文本, 是否修改)。"""
    lines = text.split("\n")
    # 找到题曰行
    for i, line in enumerate(lines):
        if line.strip().startswith("题曰"):
            # 收集题曰后的所有内容直到空行/正文
            rest = line.strip()[len("题曰：") :].strip() if "：" in line else line.strip()[len("题曰"):].strip()
            # 如果题曰行本身就是"题曰："且下一行是诗，且诗多句分行 → 已规范
            if rest == "" and i + 1 < len(lines) and lines[i + 1].strip():
                # 检查下一行是否已是规范（一联一行）
                return text, False
            if not rest:
                # 题曰： 后空 → 看下一行
                j = i + 1
                poem_lines = []
                while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith("话说"):
                    poem_lines.append(lines[j].strip())
                    j += 1
                if len(poem_lines) >= 2:
                    return text, False  # 已是分行格式
                if poem_lines:
                    # 诗在一行内，拆联
                    poems = split_poem(poem_lines[0])
                    new_block = ["题曰："] + poems
                    return "\n".join(lines[:i] + new_block + lines[j:]), True
            else:
                # 题曰和诗在同一行
                poems = split_poem(rest)
                new_block = ["题曰："] + poems
                return "\n".join(lines[:i] + new_block + lines[i + 1 :]), True
    return text, False


def split_poem(poem: str) -> list[str]:
    """把连续诗句拆成联（按句号/分号/逗号成对切分）。

    输入: "诗一，诗二。诗三，诗四。"
    输出: ["诗一，诗二。", "诗三，诗四。"]
    """
    poem = poem.strip()
    if not poem:
        return []
    # 按句号/分号切分为"联"
    pairs = re.split(r"(?<=[。；])", poem)
    pairs = [p.strip() for p in pairs if p.strip()]
    if not pairs:
        # 无句号：按逗号成对切
        clauses = [c.strip() for c in poem.split("，") if c.strip()]
        pairs = []
        for k in range(0, len(clauses), 2):
            pair = "，".join(clauses[k : k + 2])
            if pair:
                pairs.append(pair + ("。" if k + 2 >= len(clauses) else ""))
    return pairs or [poem]


def main() -> int:
    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    changed = 0
    for g in db.query(GeneratedChapter).order_by(GeneratedChapter.num).all():
        new_text, modified = normalize(g.content)
        if modified:
            g.content = new_text
            db.commit()
            changed += 1
            head = new_text.split("\n")[0]
            print(f"ch{g.num}: 规范化 ✅ {head[:30]!r}", flush=True)
        else:
            print(f"ch{g.num}: 已规范", flush=True)
    print(f"\n共规范化 {changed} 回")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
