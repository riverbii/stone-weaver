from __future__ import annotations

import re

from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..models import Base

CHAPTER_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十百零〇\d]+)\s*回(?:\s+(.*))?$")


def clean_text(text: str) -> str:
    """统一空白：全角空格转半角、折叠连续空行、去掉控制字符。"""
    text = text.replace("\u3000", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.rstrip() for line in text.splitlines()]
    out: list[str] = []
    blank = 0
    for line in lines:
        if not line.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(line)
    return "\n".join(out).strip()


def split_chapters(text: str) -> list[tuple[int, str, str]]:
    """把整本 txt 按"第N回"切分成回目列表。

    返回 [(回数, 标题, 正文)]。标题可能为空（需要人工/后续补全）。
    """
    cleaned = clean_text(text)
    lines = cleaned.splitlines()
    chapters: list[tuple[int, str, list[str]]] = []
    current_num: int | None = None
    current_title = ""
    current_body: list[str] = []

    def flush() -> None:
        if current_num is not None:
            chapters.append((current_num, current_title, current_body))

    for line in lines:
        m = CHAPTER_RE.match(line)
        if m:
            flush()
            current_num = cn_to_int(m.group(1))
            current_title = (m.group(2) or "").strip()
            current_body = []
        elif current_num is not None:
            current_body.append(line)
    flush()

    return [(num, title, "\n".join(body).strip()) for num, title, body in chapters]


_CN_DIGITS = {
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


def cn_to_int(s: str) -> int:
    """中文/阿拉伯数字回数转 int，如 '十二' -> 12。"""
    if s.isdigit():
        return int(s)
    total = 0
    section = 0
    for ch in s:
        if ch == "十":
            section = section * 10 if section else 10
            total += section
            section = 0
        elif ch == "零" or ch == "〇":
            section = 0
        elif ch in _CN_DIGITS:
            section = _CN_DIGITS[ch]
        else:
            continue
    return total + section


def make_engine(path: str) -> Engine:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine


def make_session(path: str) -> Session:
    engine = make_engine(path)
    return sessionmaker(bind=engine)()
