#!/usr/bin/env python3
"""从 ctext.org 抓取《红楼梦》程乙本前80回。

ctext 每回一个页面（/hongloumeng/chN），正文在多个 <td class="ctext"> 内，天然分段。
用法: .venv/bin/python scripts/fetch_ctext.py [--limit 80]
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from stone_weaver.models import Chapter
from stone_weaver.ingest.text import make_session, clean_text

DB = ROOT / "data" / "db" / "stone.db"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            wait = 8 * (attempt + 1)
            print(f"  重试({attempt + 1}) 等{wait}s: {e}")
            time.sleep(wait)
    raise RuntimeError(f"抓取失败: {url}")


def extract_chapter(html_text: str) -> tuple[str, list[str]]:
    """提取 (标题, 段落列表)。"""
    ctexts = re.findall(r'<td class="ctext">(.*?)</td>', html_text, re.S)
    paras = []
    for c in ctexts:
        text = html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
        text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
        if text:
            paras.append(text)
    # 标题从 description/meta 提取中文回目对（如 "甄士隱夢幻識通靈　賈雨村風塵懷閨秀"）
    m = re.search(
        r"([\u4e00-\u9fff]{2,12}[\u3000　][\u4e00-\u9fff]{2,12})(?:\s*[,-]|$)",
        html_text,
    )
    title = ""
    if m:
        title = m.group(1).replace("\u3000", " ")
    return title, paras


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()

    chapters: list[tuple[int, str, str]] = []
    for n in range(1, args.limit + 1):
        page = fetch(f"https://ctext.org/hongloumeng/ch{n}")
        title, paras = extract_chapter(page)
        body = "\n".join(paras)
        if not body:
            print(f"  !! ch{n} 正文为空")
            continue
        chapters.append((n, title, clean_text(body)))
        print(f"  ch{n} ok ({len(body)}字, {len(paras)}段) {title[:20]}")
        time.sleep(1.5)

    session: Session = make_session(str(DB))
    try:
        session.query(Chapter).filter(Chapter.version == "chengyi").delete()
        session.commit()
        for n, title, body in chapters:
            session.add(Chapter(num=n, title=title, version="chengyi", content=body))
        session.commit()
        print(f"入库完成: version=chengyi, {len(chapters)} 回 -> {DB}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
