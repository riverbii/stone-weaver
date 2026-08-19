#!/usr/bin/env python3
"""把 癸酉本阅读器导出为纯静态站（Cloudflare Pages 用）。

用法: .venv/bin/python scripts/build_static.py
产出: public/ 目录 —— index.html + chapter/{num}/index.html + static/
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from stone_weaver.web.app import app

PUBLIC = ROOT / "public"
STATIC_SRC = ROOT / "stone_weaver" / "static"
STATIC_DST = PUBLIC / "static"


def _all_character_ids() -> list[int]:
    from stone_weaver.ingest.text import make_session
    from stone_weaver.models import Character

    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    try:
        ids = [c.id for c in db.query(Character).order_by(Character.id)]
    finally:
        db.close()
    return ids


def _all_engine_nums() -> list[int]:
    from stone_weaver.ingest.text import make_session
    from stone_weaver.models import GeneratedChapter

    db = make_session(str(ROOT / "data" / "db" / "stone.db"))
    try:
        nums = [n for (n,) in db.query(GeneratedChapter.num).order_by(GeneratedChapter.num)]
    finally:
        db.close()
    return nums


def main() -> int:
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    STATIC_DST.mkdir(parents=True)
    shutil.copytree(STATIC_SRC, STATIC_DST, dirs_exist_ok=True)

    client = TestClient(app)
    count = 0

    for path, out in [
        ("/", PUBLIC / "index.html"),
        *[
            ("/chapter/%d" % n, PUBLIC / "chapter" / str(n) / "index.html")
            for n in range(1, 109)
        ],
        *[
            ("/compare/%d" % n, PUBLIC / "compare" / str(n) / "index.html")
            for n in range(1, 121)
        ],
        ("/world", PUBLIC / "world" / "index.html"),
        *[
            ("/world/chapter/%d" % n, PUBLIC / "world" / "chapter" / str(n) / "index.html")
            for n in range(1, 81)
        ],
        *[
            (
                "/world/character/%d" % cid,
                PUBLIC / "world" / "character" / str(cid) / "index.html",
            )
            for cid in _all_character_ids()
        ],
        *[
            ("/engine/%d" % n, PUBLIC / "engine" / str(n) / "index.html")
            for n in _all_engine_nums()
        ],
    ]:
        r = client.get(path)
        if r.status_code != 200:
            print(f"!! {path} -> {r.status_code}")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(r.text, encoding="utf-8")
        count += 1

    # Cloudflare Pages 404 页
    r = client.get("/chapter/999")
    if r.status_code == 404:
        (PUBLIC / "404.html").write_text(r.text, encoding="utf-8")

    print(f"静态导出完成: {count} 页 -> {PUBLIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
