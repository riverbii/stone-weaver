#!/usr/bin/env python3
"""从汉典古籍抓取《红楼梦》（庚辰底本校订本）前80回。

用法: .venv/bin/python scripts/fetch_zdic.py [--limit 80]
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

# 目录页抓到的回目链接（按顺序）
CATALOG = "https://gj.zdic.net/jibu/961/"
# 回目 URL（从目录页解析）
CHAPTER_URLS: list[tuple[int, str, str]] = []  # (num, url, title)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            wait = 5 * (attempt + 1)
            print(f"  重试({attempt + 1}) 等{wait}s: {e}")
            time.sleep(wait)
    raise RuntimeError(f"抓取失败: {url}")


def parse_catalog() -> list[tuple[int, str, str]]:
    html_text = fetch(CATALOG)
    links = re.findall(
        r'href="(/jibu/961/(\d+)\.html)"[^>]*>\s*第[一二三四五六七八九十百零〇\d]+回',
        html_text,
    )
    # 用 URL 编号推导回数：编号连续，第 n 回 = 31558 + n
    seen: dict[int, str] = {}
    for url, num_str in links:
        num = int(num_str)
        chapter = num - 31558
        if chapter not in seen:
            seen[chapter] = "https://gj.zdic.net" + url
    out = sorted((n, u, "") for n, u in seen.items())
    return out


def cn_to_int(s: str, cn: dict) -> int:
    if s.isdigit():
        return int(s)
    total, section = 0, 0
    for ch in s:
        if ch == "十":
            section = section * 10 if section else 10
            total += section
            section = 0
        elif ch in cn and cn[ch] == 0:
            section = 0
        elif ch in cn:
            section = cn[ch]
    return total + section


def extract_body(html_text: str) -> str:
    """提取正文（<p> 段落，保留分段换行），去掉导航/脚本尾巴。"""
    ps = re.findall(r"<p>(.*?)</p>", html_text, re.S)
    paras = []
    for p in ps:
        text = html.unescape(re.sub(r"<[^>]+>", "", p))
        text = text.strip()
        if text:
            paras.append(text)
    body = "\n".join(paras)
    # 去掉 JS 尾巴（从"');"或分号+脚本开始）
    body = re.split(r"\);|// 将|newText|\$\(|function|document\.", body)[0]
    # 去掉末尾残留的引号/分号
    body = body.rstrip("'\"；;")
    return clean_text(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()

    catalog = parse_catalog()
    print(f"目录共 {len(catalog)} 回")

    chapters: list[tuple[int, str, str]] = []
    for n, url, _ in catalog[: args.limit]:
        page = fetch(url)
        body = extract_body(page)
        # 标题从回目页 <title> 提取
        m = re.search(r"<title>(.*?)</title>", page)
        title = m.group(1) if m else ""
        title = re.sub(r"\s*-\s*漢典古籍.*$", "", title).strip()
        title = re.sub(r"^第[一二三四五六七八九十百零〇\d]+回\s*", "", title)
        chapters.append((n, title, body))
        print(f"  ch{n} ok ({len(body)} 字) {title[:20]}")
        time.sleep(0.8)

    # 入库
    from stone_weaver.ingest.text import make_engine

    engine = make_engine(str(DB))
    session: Session = make_session(str(DB))
    try:
        session.query(Chapter).filter(Chapter.version == "zdic").delete()
        session.commit()
        for n, title, body in chapters:
            session.add(Chapter(num=n, title=title, version="zdic", content=body))
        session.commit()
        print(f"入库完成: version=zdic, {len(chapters)} 回 -> {DB}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
