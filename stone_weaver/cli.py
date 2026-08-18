from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ingest.text import make_session, split_chapters
from .models import Chapter, Character


def cmd_ingest(args: argparse.Namespace) -> None:
    path = Path(args.file)
    text = path.read_text(encoding=args.encoding)
    chapters = split_chapters(text)
    if not chapters:
        print(f"未解析到任何回目，文件可能不是预期的格式: {path}")
        sys.exit(1)
    db = make_session(args.db)
    existing = {
        c.num for c in db.query(Chapter).filter(Chapter.version == args.version)
    }
    added = 0
    for num, title, content in chapters:
        if num in existing:
            continue
        db.add(Chapter(num=num, title=title, version=args.version, content=content))
        added += 1
    db.commit()
    print(f"{args.version}: 解析 {len(chapters)} 回，新增入库 {added} 回 -> {args.db}")


def cmd_stats(args: argparse.Namespace) -> None:
    db = make_session(args.db)
    by_version: dict[str, int] = {}
    for c in db.query(Chapter):
        by_version[c.version] = by_version.get(c.version, 0) + 1
    print("回目统计:", by_version)
    n_chars = db.query(Character).count()
    print("人物数量:", n_chars)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stone-weaver")
    sub = p.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser("ingest", help="把整本 txt 按回目导入数据库")
    ingest.add_argument("file", help="原文 txt 路径")
    ingest.add_argument(
        "--version",
        required=True,
        choices=["gongban", "guiyou"],
        help="gongban=公版 / guiyou=癸酉本",
    )
    ingest.add_argument("--db", default="data/db/stone.db", help="sqlite 路径")
    ingest.add_argument("--encoding", default="utf-8", help="文件编码")
    ingest.set_defaults(func=cmd_ingest)

    stats = sub.add_parser("stats", help="查看数据库统计")
    stats.add_argument("--db", default="data/db/stone.db")
    stats.set_defaults(func=cmd_stats)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
