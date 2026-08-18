#!/usr/bin/env python3
"""把 PDF 提取的 43 字硬切碎片行重构为语义段落（对齐维基文库分段风格）。

规则：
  - 连续碎片行合并，直到遇到"段末"标记：。！？ 或 引号闭合 + 感叹/问号
  - 偈语/诗（短行、以句读结尾）单独成段
  - 冒号引出的对话（说/道/云 + ：+ 「）可并入前段或自成段

用法: .venv/bin/python scripts/rebuild_paras.py [--num N] [--version gongban|gongban_clean]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from stone_weaver.models import Chapter
from stone_weaver.ingest.text import make_session, clean_text

DB = ROOT / "data" / "db" / "stone.db"

# 段末标点：句号/感叹/问号/分号 + 可选引号闭合
SENT_END = re.compile(r"[。！？；」』”’]+$")
# 短诗句（无"说/道/云/问"引导，像诗）
POEM_LINE = re.compile(r"^[\u4e00-\u9fff，。！？、]{4,30}$")


def rebuild(text: str) -> str:
    """碎片行 → 语义段落（先剔除页眉噪音行）。"""
    PAGE_NOISE = {
        "曹",
        "雪",
        "芹",
        "《 红 楼 梦 》",
        "《 脂 评 汇 校 石 头 记 》",
    }
    raw = []
    for l in text.split("\n"):
        s = l.strip()
        if not s:
            continue
        if re.match(r"^第\d+页$", s) or s in PAGE_NOISE:
            continue
        raw.append(s)
    paras: list[str] = []
    buf = ""
    CONNECTORS = (
        "亦",
        "又",
        "故",
        "因此",
        "所以",
        "便",
        "且",
        "况",
        "再",
        "只",
        "这",
        "那",
    )
    for i, line in enumerate(raw):
        if not buf:
            buf = line
            continue
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        buf_ends = SENT_END.search(buf)
        open_quote = buf.count("“") - buf.count("”") + buf.count("「") - buf.count("」")
        if open_quote > 0:
            buf += line
            continue
        if buf_ends and len(buf) > 20:
            is_continuation = bool(
                nxt
                and (
                    nxt.startswith(("“", "「", "‘", "『"))
                    or nxt.startswith(CONNECTORS)
                    or POEM_LINE.match(nxt)
                )
            )
            if is_continuation:
                buf += line
                continue
            paras.append(buf)
            buf = line
            continue
        buf += line
    if buf:
        paras.append(buf)
    return "\n".join(p.strip() for p in paras if p.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--num", type=int, default=1)
    ap.add_argument("--version", default="gongban")
    ap.add_argument("--out", help="写回版本（默认同 version，覆盖）")
    args = ap.parse_args()

    out_version = args.out or args.version
    session: Session = make_session(str(DB))
    try:
        ch = (
            session.query(Chapter)
            .filter(Chapter.version == args.version, Chapter.num == args.num)
            .one_or_none()
        )
        if ch is None:
            print(f"!! {args.version} ch{args.num} 不存在")
            return 1
        new = rebuild(ch.content)
        new_paras = [p for p in new.split("\n") if p.strip()]
        print(f"重构: {len(ch.paragraphs)} 段 -> {len(new_paras)} 段")
        for p in new_paras[:5]:
            print(f"  [{len(p)}字] {p[:45]}...")
        existing = (
            session.query(Chapter)
            .filter(Chapter.version == out_version, Chapter.num == args.num)
            .one_or_none()
        )
        if existing is None:
            existing = Chapter(
                num=args.num, version=out_version, title=ch.title, content=""
            )
            session.add(existing)
        existing.title = ch.title
        existing.content = clean_text(new)
        session.commit()
        print(f"{out_version} ch{args.num} 已更新")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
