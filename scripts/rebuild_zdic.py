#!/usr/bin/env python3
"""统一 zdic（汉典校订本）分段：按句末标点切成语义段落（约 200 字/段）。

用法: .venv/bin/python scripts/rebuild_zdic.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from stone_weaver.models import Chapter
from stone_weaver.ingest.text import make_session, clean_text

DB = ROOT / "data" / "db" / "stone.db"


def split_flow(text: str, target: int = 200) -> list[str]:
    """把连续文本按句末标点切成段落，目标每段约 target 字。"""
    sents = re.findall(r"[^。！？；]+[。！？；]?|[^。！？；]+$", text)
    sents = [s.strip() for s in sents if s.strip()]
    paras: list[str] = []
    buf = ""
    for s in sents:
        if buf and len(buf) + len(s) > target:
            paras.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        paras.append(buf)
    return paras


def main() -> int:
    session: Session = make_session(str(DB))
    try:
        chs = (
            session.query(Chapter)
            .filter(Chapter.version == "zdic")
            .order_by(Chapter.num)
            .all()
        )
        for c in chs:
            new = clean_text("\n".join(split_flow(c.content)))
            if new != c.content:
                c.content = new
        session.commit()
        print(f"zdic 分段完成，共 {len(chs)} 回")
        for n in (2, 50, 100, 120):
            c = (
                session.query(Chapter)
                .filter(Chapter.version == "zdic", Chapter.num == n)
                .first()
            )
            if c:
                ps = [p for p in c.paragraphs if p.strip()]
                print(f"  ch{n}: {len(ps)} 段")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
