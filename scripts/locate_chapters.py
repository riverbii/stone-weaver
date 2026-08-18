#!/usr/bin/env python3
"""定位程乙本校注本 PDF 每回的起始页（OCR 检测"第X回"标题）。

用法: .venv/bin/python scripts/locate_chapters.py <pdf路径> [输出json]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from rapidocr_onnxruntime import RapidOCR

UA_RATE = 0  # 无

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


def page_to_png(pdf: str, page: int, dpi: int = 150) -> str:
    out = tempfile.mktemp(suffix=".png")
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
            out[:-4],
        ],
        check=True,
        capture_output=True,
    )
    return out


def main() -> int:
    pdf = sys.argv[1]
    out_json = sys.argv[2] if len(sys.argv) > 2 else "/tmp/chapter_pages.json"

    # 总页数
    info = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True)
    pages = 0
    for line in info.stdout.splitlines():
        if line.startswith("Pages:"):
            pages = int(line.split(":")[1].strip())
    print(f"总页数: {pages}")

    ocr = RapidOCR()
    title_re = re.compile(r"第([一二三四五六七八九十百零〇\d]+)回")
    found: dict[int, int] = {}  # 回数 -> 页码

    # 跳过前 20 页（封面/版权/目录）
    for page in range(21, pages + 1):
        png = page_to_png(pdf, page)
        result, _ = ocr(png)
        texts = [item[1] for item in (result or [])]
        # 只查前几条文本（回目标题在页首）
        head = " ".join(texts[:4])
        m = title_re.search(head)
        if m:
            n = cn2int(m.group(1))
            if n not in found:
                found[n] = page
                print(f"  第{n}回 -> 第{page}页: {head[:30]}")
        Path(png).unlink(missing_ok=True)

    # 检查 1-120 覆盖
    missing = [n for n in range(1, 121) if n not in found]
    print(f"\n定位到 {len(found)} 回, 缺失: {missing}")
    with open(out_json, "w") as f:
        json.dump(found, f, ensure_ascii=False, indent=2)
    print(f"结果存于 {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
