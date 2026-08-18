#!/usr/bin/env python3
"""剥离汇校本（gongban）行内脂批，产出干净正文版本（gongban_clean）。

策略：
  1. 规则层：剔除 PDF 页眉噪音行（独立段落：第N页 / 曹 / 雪 / 芹 / 《 红 楼 梦 》 / 《 脂 评 汇 校 石 头 记 》）。
  2. LLM 层：对含批注标记的段落（含独立批注段与行内批注段），让 LLM 判断批注边界并剥离，
     保留正文、合并跨行续接。纯正文段原样保留。

用法:
  STONE_LLM_API_KEY=xxx .venv/bin/python scripts/clean_gongban.py [--num N] [--dry-run]

依赖: stone_weaver.llm.LLMClient（读 STONE_LLM_API_KEY / STONE_LLM_BASE_URL / STONE_LLM_MODEL）
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from stone_weaver.models import Chapter
from stone_weaver.ingest.text import make_session, clean_text

DB = ROOT / "data" / "db" / "stone.db"

# 批注前缀标记（含被 43 字换行截断的"甲\n侧："情形）
ANNOT_PREFIX = r"(?:甲侧|甲眉|甲夹|蒙侧|戚夹|戚总评|庚|靖藏|列藏|己卯|戚序|庚双|蒙双|甲双|戚双|甲|蒙|戚|庚)"
PREFIX_RE = re.compile(rf"{ANNOT_PREFIX}[:：]")

# 独立成行的页眉噪音
PAGE_NOISE_RE = re.compile(
    r"^(?:第\d+页|曹|雪|芹|《\s*红\s*楼\s*梦\s*》|《\s*脂\s*评\s*汇\s*校\s*石\s*头\s*记\s*》)$"
)

PROMPT = """你是古籍整理专家。给定《红楼梦》脂评汇校本的一段原文（可能跨多行），
其中夹杂脂砚斋批语（如"甲侧：""甲眉：""甲夹：""蒙侧：""戚夹：""戚总评：""庚："等前缀标注），
批语与正文无分隔符、可能被换行截断。请剥离全部批语，只保留正文。

规则：
1. 输出 ONLY 剥离后的正文纯文本，不要任何解释、引号、前缀。
2. 批语前缀本身（"甲侧："等）也删除。
3. 批语后的正文需要与批语前的正文无缝续接（若跨行则合并）。
4. 若整段都是批语（无正文），输出空行。
5. 不要改动正文文字，不要加标点。

原文：
{text}
"""


def has_annotation(text: str) -> bool:
    return bool(PREFIX_RE.search(text))


def clean_page_noise(paragraphs: list[str]) -> list[str]:
    return [p for p in paragraphs if not PAGE_NOISE_RE.match(p.strip())]


def run_llm(api: str, text: str) -> str:
    from stone_weaver.llm import LLMClient

    client = LLMClient()
    if not api:
        raise RuntimeError("STONE_LLM_API_KEY 未设置")
    resp = client.chat(
        [{"role": "user", "content": PROMPT.format(text=text)}],
        temperature=0.0,
    )
    return resp


def clean_one_chapter(num: int, dry_run: bool = False) -> list[str]:
    session: Session = make_session(str(DB))
    try:
        ch = (
            session.query(Chapter)
            .filter(Chapter.version == "gongban", Chapter.num == num)
            .one_or_none()
        )
        if ch is None:
            print(f"!! gongban ch{num} 不存在")
            return []
        paragraphs = ch.paragraphs
    finally:
        session.close()

    paragraphs = clean_page_noise(paragraphs)

    out: list[str] = []
    for i, p in enumerate(paragraphs):
        if not has_annotation(p):
            out.append(p)
            continue
        if dry_run:
            out.append(p)
            continue
        cleaned = run_llm("", p)
        cleaned = clean_text(cleaned)
        out.append(cleaned)
        print(f"  ch{num}[{i}] 剥离: {p[:30]}... -> {cleaned[:40]}")
        time.sleep(0.3)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--num", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true", help="只统计，不调 LLM")
    args = ap.parse_args()

    out = clean_one_chapter(args.num, dry_run=args.dry_run)
    if args.dry_run:
        n_annot = sum(1 for p in out if has_annotation(p))
        print(f"ch{args.num}: {len(out)} 段，含批注 {n_annot} 段（等待 LLM 处理）")
        return 0

    if not out:
        return 1
    body = "\n".join(out)
    session: Session = make_session(str(DB))
    try:
        existing = (
            session.query(Chapter)
            .filter(Chapter.version == "gongban_clean", Chapter.num == args.num)
            .one_or_none()
        )
        if existing is None:
            existing = Chapter(
                num=args.num,
                version="gongban_clean",
                title="",
                content="",
            )
            session.add(existing)
        existing.title = out[0].strip() if out and out[0].strip() else ""
        existing.content = clean_text(body)
        session.commit()
        print(f"gongban_clean ch{args.num} 入库: {len(existing.content)} 字")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
