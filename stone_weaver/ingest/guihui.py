#!/usr/bin/env python3
"""把 data/text/guihui.txt（按回切分）入库 stone.db，version=guihui。

用法: .venv/bin/python -m stone_weaver.ingest.guihui
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy.orm import Session

from stone_weaver.models import Chapter
from stone_weaver.ingest.text import clean_text

DB = Path(__file__).resolve().parents[2] / "data" / "db" / "stone.db"
SRC = Path(__file__).resolve().parents[2] / "data" / "text" / "guihui.txt"

TITLE_RE = re.compile(r"^第([一二三四五六七八九十百零〇\d]+)回(.*)$")


def cn_to_int(s: str) -> int:
    if s.isdigit():
        return int(s)
    digits = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    total, section = 0, 0
    for ch in s:
        if ch == "十":
            section = section * 10 if section else 10
            total += section
            section = 0
        elif ch in digits:
            section = digits[ch]
    return total + section


def parse(src: Path) -> list[tuple[int, str, str]]:
    chapters: list[tuple[int, str, list[str]]] = []
    cur: tuple[int, str, list[str]] | None = None
    for line in src.read_text(encoding="utf-8").splitlines():
        m = TITLE_RE.match(line)
        if m and "\u3000" in (m.group(2) or ""):
            if cur is not None:
                chapters.append(cur)
            cur = (cn_to_int(m.group(1)), m.group(2).strip(), [])
        elif cur is not None:
            cur[2].append(line)
    if cur is not None:
        chapters.append(cur)
    return [(n, t, clean_text("\n".join(b))) for n, t, b in chapters]


def main() -> int:
    chapters = parse(SRC)
    nums = [n for n, _, _ in chapters]
    assert len(chapters) == 108, f"回数不对: {len(chapters)}"
    assert sorted(nums) == list(range(1, 109)), "回数不连续"
    print(f"解析 {len(chapters)} 回，总字数 {sum(len(c) for _, _, c in chapters)}")

    from stone_weaver.ingest.text import make_engine, make_session

    engine = make_engine(str(DB))
    session: Session = make_session(str(DB))
    try:
        # 删掉旧的 guihui 版本（幂等）
        session.query(Chapter).filter(Chapter.version == "guihui").delete()
        session.commit()
        for num, title, content in chapters:
            session.add(
                Chapter(num=num, title=title, version="guihui", content=content)
            )
        session.commit()
        print(f"入库完成: {DB} (version=guihui, {len(chapters)} 回)")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
