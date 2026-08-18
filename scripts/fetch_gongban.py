#!/usr/bin/env python3
"""从维基文库抓取公版《红楼梦》前80回多版本文本。

版本与数据源：
  chengjia  —— 紅樓夢（程甲本），逐回页面，渲染 HTML 提取
  chengyi   —— 紅樓夢（程乙本），每 10 回一页，wikitext 提取
  gengchen  —— 紅樓夢/第NNN回（前80回庚辰底本数字化汇校），wikitext 提取

用法: .venv/bin/python scripts/fetch_gongban.py [--limit N]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from stone_weaver.models import Chapter
from stone_weaver.ingest.text import clean_text

API = "https://zh.wikisource.org/w/api.php"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

DB = ROOT / "data" / "db" / "stone.db"

CN = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "〇": 0,
    "零": 0,
}


def api_get(params: dict) -> dict:
    params["format"] = "json"
    url = API + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(8):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                # 403/429 限流：指数退避 + 长等待
                wait = 15 * (attempt + 1)
                print(f"  限流({e.code}), 等待 {wait}s (第{attempt + 1}次重试)")
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            last_err = e
            time.sleep(10)
    raise RuntimeError(f"限流重试失败: {last_err}")


def fetch_wikitext(title: str) -> str | None:
    d = api_get({"action": "parse", "page": title, "prop": "wikitext"})
    return d.get("parse", {}).get("wikitext", {}).get("*")


def fetch_rendered(title: str) -> str | None:
    d = api_get({"action": "parse", "page": title, "prop": "text"})
    return d.get("parse", {}).get("text", {}).get("*")


def strip_html(html_text: str) -> str:
    """渲染 HTML → 纯文本：删 CSS、标签、实体、导航噪音。"""
    html_text = re.sub(r"\.mw-parser-output[^{]*\{[^}]*\}", "", html_text)
    text = html.unescape(re.sub(r"<[^>]+>", "", html_text))
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    noise = {
        "目錄",
        "紅樓夢（程甲本）",
        "全書始",
        "下一回▶",
        "上一回▶",
        "下一回",
        "上一回",
        "回目錄",
        "返回",
    }
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s in noise:
            continue
        lines.append(s)
    return "\n".join(lines)


def extract_wikitext_chapters(wt: str) -> list[tuple[int, str]]:
    """从 wikitext 切出 (回数, 正文)。标题行形如 '==第N回 标题== 正文'。"""
    # 先去掉 header 模板块（{{header ... }}）
    wt = re.sub(r"\{\{header\b.*?\n\}\}", "", wt, flags=re.S)
    # 去掉其它顶层模板调用（{{...}} 单层）——粗暴但够用，正文里的 {{~~}} 保留
    parts: list[tuple[int, str]] = []
    # 按 ==第N回== 切
    splits = re.split(
        r"\n?==\s*第([一二三四五六七八九十百零〇\d]+)回\s*(.*?)\s*==\s*", wt
    )
    # splits: [前导, num1, title1, body1, num2, title2, body2, ...]
    for i in range(1, len(splits) - 1, 3):
        num = cn_to_int(splits[i])
        body = splits[i + 2] if i + 2 < len(splits) else ""
        parts.append((num, clean_wikitext(body)))
    return parts


def clean_wikitext(body: str) -> str:
    """wikitext 正文清理：去引用标记、模板、链接，保留正文。"""
    body = re.sub(r"<ref[^>]*>.*?</ref>", "", body, flags=re.S)
    body = re.sub(r"<ref[^>]*/>", "", body)
    body = re.sub(r"\{\{~~\|(.*?)\}\}", r"\1", body, flags=re.S)
    body = re.sub(r"\{\{(?:center|poem|rh)\|(.*?)\}\}", r"\1", body, flags=re.S)
    body = re.sub(r"\{\{[^{}]*\}\}", "", body)
    body = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", body)
    body = re.sub(r"\[\[([^\]]*)\]\]", r"\1", body)
    body = re.sub(r"\-{云|}\-", "", body)
    body = body.replace("~~~~", "")
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", body)
    return clean_text(body)


def cn_to_int(s: str) -> int:
    if s.isdigit():
        return int(s)
    total = 0
    section = 0
    for ch in s:
        if ch == "十":
            section = section * 10 if section else 10
            total += section
            section = 0
        elif ch in CN:
            v = CN[ch]
            if v == 0:
                section = 0
            else:
                section = v
        else:
            continue
    return total + section


def cn_num_to_digits(n: int) -> str:
    """1 → '一', 12 → '十二', 21 → '二十一'（程甲本页名用汉字序号）"""
    digits = {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
    }
    if n <= 10:
        if n == 10:
            return "十"
        return digits[n]
    tens, ones = divmod(n, 10)
    prefix = digits[tens] if tens > 1 else ""
    if ones == 0:
        return f"{prefix}十"
    return f"{prefix}十{digits[ones]}"


def page_name_for_chapter(n: int) -> str:
    """程甲本每回一个页面，页名用汉字（十/二十/二十一…），对应回数。"""
    special = {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
    }
    if n in special:
        return special[n]
    return cn_num_to_digits(n)


# ---- 各版本抓取器 ----


def fetch_chengjia(limit: int) -> list[tuple[int, str]]:
    out = []
    for n in range(1, min(81, limit + 1)):
        title = f"紅樓夢（程甲本）/{page_name_for_chapter(n)}"
        h = fetch_rendered(title)
        if not h:
            print(f"  !! ch{n} 抓取失败")
            continue
        body = strip_html(h)
        out.append((n, body))
        print(f"  chengjia ch{n} ok ({len(body)} 字)")
        time.sleep(5)
    return out


def fetch_chengyi(limit: int) -> list[tuple[int, str]]:
    # 程乙本每 10 回一页：第一回 至第十回、第十一回 至第二十回…
    out = []
    ranges = [
        (1, "第一回", "第十回"),
        (11, "第十一回", "第二十回"),
        (21, "第二十一回", "第三十回"),
        (31, "第三十一回", "第四十回"),
        (41, "第四十一回", "第五十回"),
        (51, "第五十一回", "第六十回"),
        (61, "第六十一回", "第七十回"),
        (71, "第七十一回", "第八十回"),
    ]
    for start, s1, s2 in ranges:
        if start > limit:
            break
        title = f"紅樓夢（程乙本）/{s1}　至{s2}"
        wt = fetch_wikitext(title)
        if not wt:
            print(f"  !! 程乙本 {s1}~{s2} 抓取失败")
            continue
        for num, body in extract_wikitext_chapters(wt):
            if start <= num < start + 10 and num <= limit:
                out.append((num, body))
                print(f"  chengyi ch{num} ok ({len(body)} 字)")
        time.sleep(5)
    return out


def fetch_gengchen(limit: int) -> list[tuple[int, str]]:
    out = []
    for n in range(1, min(81, limit + 1)):
        title = f"紅樓夢/第{n:03d}回"
        wt = fetch_wikitext(title)
        if not wt:
            print(f"  !! ch{n} 抓取失败")
            continue
        # 分回页面直接是正文，找标题行和正文
        body = clean_wikitext(wt)
        out.append((n, body))
        print(f"  gengchen ch{n} ok ({len(body)} 字)")
        time.sleep(5)
    return out


def ingest(version: str, chapters: list[tuple[int, str]]) -> None:
    from stone_weaver.ingest.text import make_engine, make_session

    engine = make_engine(str(DB))
    session: Session = make_session(str(DB))
    try:
        session.query(Chapter).filter(Chapter.version == version).delete()
        session.commit()
        for num, content in chapters:
            # 标题从正文首行提取（回目行）
            first = content.splitlines()[0] if content.splitlines() else ""
            title = re.sub(
                r"^\s*第[一二三四五六七八九十百零〇\d]+回\s*", "", first
            ).strip()
            body = (
                "\n".join(content.splitlines()[1:]) if content.splitlines() else content
            )
            session.add(
                Chapter(num=num, title=title, version=version, content=body.strip())
            )
        session.commit()
        print(f"入库完成: version={version}, {len(chapters)} 回 -> {DB}")
    finally:
        session.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--versions", default="chengjia,chengyi,gengchen")
    args = ap.parse_args()

    for v in args.versions.split(","):
        print(f"\n=== 抓取 {v} ===")
        fetchers = {
            "chengjia": fetch_chengjia,
            "chengyi": fetch_chengyi,
            "gengchen": fetch_gengchen,
        }
        chapters = fetchers[v](args.limit)
        if not chapters:
            print("  无数据，跳过")
            continue
        ingest(v, chapters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
