#!/usr/bin/env python3
"""生成影印阅读器数据：按页保存扫描图 + OCR 文本。

结构:
  data/fax/<version>/<chapter>/page-<nnn>.png
  data/fax/<version>/<chapter>/page-<nnn>.txt
  data/fax/<version>/index.json    # 回目 -> 页码范围

用法: .venv/bin/python scripts/build_fax.py <pdf路径> <version> <定位json>
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rapidocr_onnxruntime import RapidOCR

FAX_DIR = ROOT / "data" / "fax"


def main() -> int:
    pdf = sys.argv[1]
    version = sys.argv[2]
    loc_json = sys.argv[3]

    found = json.load(open(loc_json))
    found = {int(k): v for k, v in found.items()}
    sorted_pages = sorted(found.items())

    out = FAX_DIR / version
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # 回目标题（从 DB 读取对应版本标题）
    from stone_weaver.ingest.text import make_session
    from stone_weaver.models import Chapter

    session = make_session(str(ROOT / "data" / "db" / "stone.db"))
    titles = {}
    try:
        for num, _ in sorted_pages:
            c = (
                session.query(Chapter)
                .filter(Chapter.version == "zdic", Chapter.num == num)
                .first()
            )
            titles[num] = c.title if c else f"第{num}回"
    finally:
        session.close()

    from sqlalchemy.orm import Session  # noqa

    ocr = RapidOCR()
    index: dict[str, dict] = {}

    # 总页数
    info = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True)
    pages = 0
    for line in info.stdout.splitlines():
        if line.startswith("Pages:"):
            pages = int(line.split(":")[1].strip())

    for idx, (num, start) in enumerate(sorted_pages):
        end = sorted_pages[idx + 1][1] - 1 if idx + 1 < len(sorted_pages) else pages
        chap_dir = out / str(num)
        chap_dir.mkdir(parents=True, exist_ok=True)
        page_info = []
        for page in range(start, end + 1):
            png = chap_dir / f"page-{page:03d}.png"
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-r",
                    "150",
                    "-png",
                    pdf,
                    str(png)[:-4],
                ],
                check=True,
                capture_output=True,
            )
            # 实际文件名带 -NNN
            import glob

            files = glob.glob(str(png)[:-4] + "*.png")
            if not files:
                continue
            real = Path(files[0])
            if real != png:
                real.rename(png)
            # OCR 文本
            result, _ = ocr(str(png))
            lines = []
            if result:
                rows = {}
                for item in result:
                    box, text, _ = item
                    y = box[0][1] // 25 * 25
                    rows.setdefault(y, []).append((box[0][0], text))
                for y in sorted(rows):
                    lines.append(" ".join(t for _, t in sorted(rows[y])))
            (chap_dir / f"page-{page:03d}.txt").write_text(
                "\n".join(lines), encoding="utf-8"
            )
            page_info.append({"page": page, "file": f"page-{page:03d}.png"})
        index[str(num)] = {
            "title": titles.get(num, ""),
            "start": start,
            "end": end,
            "pages": page_info,
        }
        print(f"  第{num}回 页{start}-{end} ({len(page_info)}页)")

    (out / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"影印数据生成: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
