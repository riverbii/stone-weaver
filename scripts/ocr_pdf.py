#!/usr/bin/env python3
"""程乙本校注本：定位120回起始页 + 逐回OCR入库。

流程：
  1. 扫描全书找"第X回"标题页（跳过前63页目录区）
  2. 每回从起始页到下一回前，逐页 OCR，拼接正文
  3. 入库 version=chengyi_ocr

用法: .venv/bin/python scripts/ocr_chengyi.py
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from stone_weaver.models import Chapter
from stone_weaver.ingest.text import make_session, clean_text

PDF = None
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


def cn2int(s: str) -> int:
    if s.isdigit():
        return int(s)
    total, section = 0, 0
    for ch in s:
        if ch == "十":
            section = section * 10 if section else 10
            total += section
            section = 0
        elif ch in CN and CN[ch] == 0:
            section = 0
        elif ch in CN:
            section = CN[ch]
    return total + section


def page_png(pdf: str, page: int, dpi: int = 150) -> str:
    prefix = tempfile.mktemp(prefix="ocr_", suffix="")
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            str(dpi),
            "-png",
            pdf,
            prefix,
        ],
        check=True,
        capture_output=True,
    )
    files = glob.glob(prefix + "*.png")
    return files[0] if files else ""


def locate_chapters(ocr, pdf: str, pages: int, start_page: int = 64) -> dict[int, int]:
    """扫描找每回起始页。返回 {回数: 页码}。"""
    # 回首特征：整页文本中"第X回"后跟对仗回目（间隔符·/空格，前后各有2-12字）
    title_re = re.compile(
        r"第([一二三四五六七八九十百零〇\d]+)回[\u3000\s·．\.]{1,3}"
        r"([\u4e00-\u9fff]{2,12})[\u3000\s·．\.]{1,3}([\u4e00-\u9fff]{2,12})"
    )
    found: dict[int, int] = {}
    for page in range(start_page, pages + 1):
        png = page_png(pdf, page)
        if not png:
            continue
        result, _ = ocr(png)
        texts = [item[1] for item in (result or [])]
        full = "".join(texts)
        # 只查页首区域（前2块文本），避免正文中的引用误报
        head = " ".join(texts[:3])
        m = title_re.search(head)
        if m:
            n = cn2int(m.group(1))
            if n not in found:
                found[n] = page
                print(f"  第{n}回 -> 第{page}页 | {m.group(2)}{m.group(3)}")
        os.unlink(png)
        if page % 50 == 0:
            print(f"  已扫 {page}/{pages} 页, 定位 {len(found)} 回")
    return found


def ocr_page_lines(ocr, png: str) -> list[str]:
    """OCR 一页，按行重组。"""
    result, _ = ocr(png)
    if not result:
        return []
    rows: dict[int, list[tuple[int, str]]] = {}
    for item in result:
        box, text, _ = item
        y = box[0][1] // 25 * 25
        rows.setdefault(y, []).append((box[0][0], text))
    lines = []
    for y in sorted(rows):
        line = " ".join(t for _, t in sorted(rows[y]))
        lines.append(line)
    return lines


def main() -> int:
    global PDF, VERSION
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--version", default="ocr_pdf")
    ap.add_argument("--start", type=int, default=64, help="正文起始页(跳过目录)")
    args = ap.parse_args()
    PDF = args.pdf
    VERSION = args.version
    info = subprocess.run(["pdfinfo", str(PDF)], capture_output=True, text=True)
    pages = 0
    for line in info.stdout.splitlines():
        if line.startswith("Pages:"):
            pages = int(line.split(":")[1].strip())
    print(f"程乙本校注本 总页数: {pages}")

    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR()

    found = locate_chapters(ocr, str(PDF), pages, start_page=args.start)
    missing = [n for n in range(1, 121) if n not in found]
    print(f"定位 {len(found)} 回, 缺失 {missing}")

    # 补齐缺失回（用前后回插值）
    sorted_pages = sorted(found.items())
    if not sorted_pages:
        print("无定位结果，退出")
        return 1

    # 逐回 OCR
    session: Session = make_session(str(DB))
    try:
        session.query(Chapter).filter(Chapter.version == VERSION).delete()
        session.commit()
        for idx, (num, start) in enumerate(sorted_pages):
            end = sorted_pages[idx + 1][1] - 1 if idx + 1 < len(sorted_pages) else pages
            paras: list[str] = []
            title = ""
            for page in range(start, end + 1):
                png = page_png(str(PDF), page)
                if not png:
                    continue
                lines = ocr_page_lines(ocr, png)
                for line in lines:
                    s = line.strip()
                    if not s:
                        continue
                    if s.startswith("中国古典文学名著"):
                        continue
                    # 回目行（第X回 + 回目对）→ 提取标题并剔除
                    tm = re.match(r"^第[一二三四五六七八九十百零〇\d]+回[\u3000\s]*(.+)$", s)
                    if tm:
                        if not title:
                            title = tm.group(1).strip()
                        continue
                    paras.append(s)
                os.unlink(png)
            body = clean_text("\n".join(paras))
            session.add(
                Chapter(num=num, title=title, version=VERSION, content=body)
            )
            session.commit()
            print(f"  第{num}回 入库 ({len(body)}字) 标题:{title[:20]} 页{start}-{end}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
