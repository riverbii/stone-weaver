#!/usr/bin/env python3
"""定位校验与补漏：检查 1-120 回缺失/重复，缺失回在相邻回页之间补扫描。

用法: .venv/bin/python scripts/verify_chapters.py <pdf路径> <定位json> <输出json>
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rapidocr_onnxruntime import RapidOCR

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


def page_text(ocr, pdf: str, page: int) -> str:
    prefix = tempfile.mktemp(prefix="v_", suffix="")
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            "120",
            "-png",
            pdf,
            prefix,
        ],
        check=True,
        capture_output=True,
    )
    import glob

    files = glob.glob(prefix + "*.png")
    if not files:
        return ""
    result, _ = ocr(files[0])
    Path(files[0]).unlink(missing_ok=True)
    return " ".join(item[1] for item in (result or []))


def main() -> int:
    pdf = sys.argv[1]
    loc_json = sys.argv[2]
    out_json = sys.argv[3] if len(sys.argv) > 3 else loc_json

    found = json.load(open(loc_json))
    found = {int(k): v for k, v in found.items()}

    missing = [n for n in range(1, 121) if n not in found]
    dup = [n for n, c in __import__("collections").Counter(found).items() if c > 1]
    print(f"已定位 {len(found)} 回, 缺失 {missing}, 重复 {dup}")

    if not missing:
        print("无缺失")
        return 0

    ocr = RapidOCR()
    title_re = re.compile(
        r"第([一二三四五六七八九十百零〇\d]+)回[\u3000\s·．.]{1,3}"
        r"([\u4e00-\u9fff]{2,12})"
    )
    # 对每个缺失回，在前后两回页之间扫描
    for n in missing:
        # 找前一个已定位的回
        prev = max((k for k in found if k < n), default=None)
        next_ = min((k for k in found if k > n), default=None)
        start = found.get(prev, 1) if prev else 1
        end = found.get(next_, start + 50) if next_ else start + 50
        print(f"  补扫 第{n}回: 页 {start}-{end}")
        for page in range(start, end + 1):
            t = page_text(ocr, pdf, page)
            m = title_re.search(t)
            if m and cn2int(m.group(1)) == n:
                found[n] = page
                print(f"    补到: 第{n}回 -> 第{page}页 | {m.group(2)}")
                break
    json.dump(found, open(out_json, "w"), ensure_ascii=False, indent=2)
    still = [n for n in range(1, 121) if n not in found]
    print(f"补漏后仍缺: {still}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
