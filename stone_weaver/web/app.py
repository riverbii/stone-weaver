"""癸酉本石头记 Web 阅读器。

启动: .venv/bin/uvicorn stone_weaver.web.app:app --port 8000
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..ingest.text import make_session
from ..models import Chapter, Character, Event, Location, Relationship
from .compare import (
    ANNOT_COLORS,
    VERSIONS,
    build_comparison,
    char_diff,
    char_diff_titles,
    parse_annotations,
)

ANNOTATION_RE = re.compile(r"〔批(?:[:：][^〕]*)?〕(.*?)〔/批〕", re.S)


def render_annotated(text: str) -> list[dict]:
    """把段落解析成渲染节点：批注带 source（模板按来源分色）。"""
    return parse_annotations(text)


# 各版本说明（底本 / 版本性质）
VERSION_DESC = {
    "gong": "脂评汇校本（庚辰本系为主，参校诸脂本，含脂批）",
    "zdic": "1982人民文学出版社校注本（前80回庚辰底本，后40回程甲底本，无脂批）",
    "chengjia": "程甲本（1791程伟元/高鹗活字本，120回）",
    "chengyi": "程乙本（1792程伟元/高鹗重订本，120回）",
    "gengchen": "庚辰本（脂砚斋重评石头记，庚辰定本，78回）",
    "chengyi_ocr": "程乙本OCR（欧阳健校注本PDF本地识别）",
    "hys_ocr": "红研所校注本OCR（庚辰底本PDF本地识别）",
    "fax_chengyi": "程乙本校注本影印页（贵州人民出版社PDF）",
    "fax_hys": "红研所校注本影印页（1996年版PDF）",
}


_HUIQIAN_RE = None


def _preface_paras(paragraphs: list[str]) -> tuple[list[str], list[str]]:
    """把回前批段从段落中分离，返回 (回前批段, 正文段)。"""
    global _HUIQIAN_RE
    if _HUIQIAN_RE is None:
        _HUIQIAN_RE = re.compile(r"此回中凡用|（按：|回前批|回前总评|此回亦非正文")
    prefs = []
    body = []
    for p in paragraphs:
        if _HUIQIAN_RE.search(p):
            prefs.append(p)
        else:
            body.append(p)
    return prefs, body


def _annot_ranges(text: str) -> list[tuple[int, int]]:
    """返回文本中批注内容所在的 (start, end) 区间（用于渲染时排除高亮）。

    用等长替换法：strip_annotations 把批注替换为空格，对比原文即可定位。
    """
    from .compare import strip_annotations

    cleaned = strip_annotations(text)
    if len(cleaned) != len(text):
        return []
    ranges: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != " " and cleaned[i] == " ":
            # 找到批注区间（连续空格段）
            j = i
            while j < n and cleaned[j] == " ":
                j += 1
            ranges.append((i, j))
            i = j
        else:
            i += 1
    return ranges


def _color_tokens(a: str, b: str, tokens: list[dict]) -> list[dict]:
    """批注区间内的 token 标记为 ann（夹批小字），不参与差异着色。

    逐字符切分：把每个 token 中落在批注区间内的字符切成 ann 子 token，
    其余保持原 tag。这样夹批与正文在 token 内也能区分。
    """
    ra = _annot_ranges(a)
    rb = _annot_ranges(b)

    def in_any(pos: int, ranges: list[tuple[int, int]]) -> bool:
        return any(s <= pos < e for s, e in ranges)

    out: list[dict] = []
    a_pos = 0
    b_pos = 0
    for t in tokens:
        a_text = t["a"]
        b_text = t["b"]
        # 逐字符切分 a
        a_chunks: list[dict] = []
        cur: dict | None = None
        for i, ch in enumerate(a_text):
            is_ann = in_any(a_pos + i, ra)
            if cur is None or (cur["ann"] != is_ann):
                if cur:
                    a_chunks.append(cur)
                cur = {"ann": is_ann, "text": ch}
            else:
                cur["text"] += ch
        if cur:
            a_chunks.append(cur)

        # 逐字符切分 b
        b_chunks: list[dict] = []
        cur = None
        for i, ch in enumerate(b_text):
            is_ann = in_any(b_pos + i, rb)
            if cur is None or (cur["ann"] != is_ann):
                if cur:
                    b_chunks.append(cur)
                cur = {"ann": is_ann, "text": ch}
            else:
                cur["text"] += ch
        if cur:
            b_chunks.append(cur)

        # 合并输出（以 a 的 chunk 为准，b 对应拼接）
        out_a: list[str] = []
        out_b: list[str] = []
        out_tags: list[str] = []
        a_idx = 0
        b_idx = 0
        for ac in a_chunks:
            # b 中对应长度
            blen = ac["text"].count("")  # 不可用；改为逐 token 对齐
            break

        # 简化：按 a 的 chunk 切分，b 按同样长度切（tokens 已对齐）
        out_a, out_b, out_tags = [], [], []
        a_off = 0
        b_off = 0
        for ac in a_chunks:
            n = len(ac["text"])
            b_piece = b_text[b_off : b_off + n]
            b_off += n
            tag = "ann" if ac["ann"] else t["tag"]
            if out_tags and out_tags[-1] == tag:
                out_a[-1] += ac["text"]
                out_b[-1] += b_piece
            else:
                out_a.append(ac["text"])
                out_b.append(b_piece)
                out_tags.append(tag)
        for i in range(len(out_a)):
            out.append({"a": out_a[i], "b": out_b[i], "tag": out_tags[i]})
        a_pos += len(a_text)
        b_pos += len(b_text)
    return out


def _preferred_chapter(ch, num: int):
    """优先取"重构段落"版本（gongban_rb），否则用原版。"""
    if ch.version == "gongban":
        db = get_db()
        try:
            rb = (
                db.query(Chapter)
                .filter(Chapter.version == "gongban_rb", Chapter.num == num)
                .one_or_none()
            )
            if rb is not None:
                return rb
        finally:
            db.close()
    return ch


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "db" / "stone.db"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# 影印版 PDF 与回目定位索引
FAX_SOURCES = {
    "fax_chengyi": {
        "pdf": ROOT
        / "data"
        / "红楼梦"
        / "红楼梦（程乙本）欧阳健等校注，贵州人民出版社.pdf",
        "index": ROOT / "data" / "fax" / "chengyi.json",
    },
    "fax_hys": {
        "pdf": ROOT
        / "data"
        / "红楼梦"
        / "红楼梦(红研所校注本120回 第二版)庚辰本为底本_1996年版.pdf",
        "index": ROOT / "data" / "fax" / "hys.json",
    },
}

app = FastAPI(title="stone-weaver 阅读器")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def annotate(text: str) -> str:
    """把 〔批:red〕…〔/批〕 批注标记转为内联高亮 span。"""
    return ANNOTATION_RE.sub(r'<span class="ann">\1</span>', text)


templates.env.filters["annotate"] = annotate


def get_db():
    return make_session(str(DB))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    db = get_db()
    try:
        chapters = db.query(Chapter).filter(Chapter.version == "guihui_clean").all()
    finally:
        db.close()
    return templates.TemplateResponse(
        request=request,
        name="cover.html",
        context={"chapters": chapters},
    )


@app.get("/chapter/{num}", response_class=HTMLResponse)
def chapter(request: Request, num: int):
    v = "guihui_clean"
    db = get_db()
    try:
        ch = (
            db.query(Chapter)
            .filter(Chapter.version == v, Chapter.num == num)
            .one_or_none()
        )
        all_chs = (
            db.query(Chapter.num, Chapter.title)
            .filter(Chapter.version == v)
            .order_by(Chapter.num)
            .all()
        )
        total = len(all_chs)
    finally:
        db.close()
    if ch is None:
        return templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"num": num},
            status_code=404,
        )
    prev = next_ = None
    for n, t in all_chs:
        if n == num - 1:
            prev = (n, t)
        elif n == num + 1:
            next_ = (n, t)
    paragraphs = ch.paragraphs
    annotated = [render_annotated(p) for p in paragraphs]
    return templates.TemplateResponse(
        request=request,
        name="reader_chapter.html",
        context={
            "chapter": ch,
            "paragraphs": paragraphs,
            "annotated": annotated,
            "all_chapters": all_chs,
            "prev": prev,
            "next": next_,
            "total": total,
            "version": v,
            "is_clean": v == "guihui_clean",
        },
    )


@app.get("/world", response_class=HTMLResponse)
def world(request: Request, kind: str = "story"):
    db = get_db()
    try:
        q = db.query(Character).order_by(Character.name)
        if kind in ("story", "reference"):
            q = q.filter(Character.kind == kind)
        chars = q.all()
        n_events = db.query(Event).count()
        n_rels = db.query(Relationship).count()
        n_locs = db.query(Location).count()
        n_ref = db.query(Character).filter(Character.kind == "reference").count()
    finally:
        db.close()
    return templates.TemplateResponse(
        request=request,
        name="world.html",
        context={
            "characters": chars,
            "n_chars": len(chars),
            "n_events": n_events,
            "n_rels": n_rels,
            "n_locs": n_locs,
            "n_ref": n_ref,
            "kind": kind,
        },
    )


@app.get("/fax/{key}/{num}/{page}", response_class=Response)
def fax_page(request: Request, key: str, num: int, page: int):
    """影印页：实时从 PDF 转图返回 PNG。"""
    import subprocess
    import tempfile

    src = FAX_SOURCES.get(key)
    if src is None or not src["pdf"].exists():
        return Response(status_code=404)
    prefix = tempfile.mktemp(prefix="fax_", suffix="")
    try:
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
                str(src["pdf"]),
                prefix,
            ],
            check=True,
            capture_output=True,
        )
        import glob

        files = sorted(glob.glob(prefix + "*.png"))
        if not files:
            return Response(status_code=404)
        data = Path(files[0]).read_bytes()
        return Response(content=data, media_type="image/png")
    finally:
        import glob

        for f in glob.glob(prefix + "*"):
            try:
                Path(f).unlink()
            except OSError:
                pass


@app.get("/fax/{key}/{num}", response_class=HTMLResponse)
def fax_chapter_info(request: Request, key: str, num: int):
    """影印回目信息：页码范围。"""
    src = FAX_SOURCES.get(key)
    if src is None or not src["index"].exists():
        return {"num": num, "pages": []}
    index = json.loads(src["index"].read_text())
    info = index.get(str(num))
    if info is None:
        return {"num": num, "pages": []}
    return {"num": num, "start": info["start"], "end": info["end"]}


@app.get("/world/chapter/{num}", response_class=HTMLResponse)
def world_chapter(request: Request, num: int, version: str = "gongban_rb"):
    db = get_db()
    try:
        ch = (
            db.query(Chapter)
            .filter(Chapter.version == version, Chapter.num == num)
            .one_or_none()
        )
        if ch is None:
            return templates.TemplateResponse(
                request=request,
                name="not_found.html",
                context={"num": num},
                status_code=404,
            )
        from ..world.extract import chapter_mentions

        mentions = chapter_mentions(db, ch.content)
        char_map = {c.id: c for c in db.query(Character)}
        cast = sorted(
            [
                {"char": char_map[cid], "count": n}
                for cid, n in mentions.items()
                if cid in char_map
            ],
            key=lambda r: -r["count"],
        )
    finally:
        db.close()
    return templates.TemplateResponse(
        request=request,
        name="world_chapter.html",
        context={"num": num, "title": ch.title, "cast": cast, "version": version},
    )


@app.get("/world/character/{cid}", response_class=HTMLResponse)
def world_character(request: Request, cid: int, version: str = "gongban_rb"):
    db = get_db()
    try:
        c = db.query(Character).filter(Character.id == cid).one_or_none()
        if c is None:
            return templates.TemplateResponse(
                request=request,
                name="not_found.html",
                context={"num": cid},
                status_code=404,
            )
        # 出场回分布：在哪些回被提及（规则匹配）
        from ..world.extract import names_variants

        variants = names_variants([c])
        words = variants.get(c.id, [])
        appear = []
        if words:
            for ch in (
                db.query(Chapter)
                .filter(Chapter.version == version)
                .order_by(Chapter.num)
                .all()
            ):
                n = sum(ch.content.count(w) for w in words)
                if n:
                    appear.append({"num": ch.num, "title": ch.title, "count": n})
        rels_out = db.query(Relationship).filter(Relationship.source_id == c.id).all()
        rels_in = db.query(Relationship).filter(Relationship.target_id == c.id).all()
    finally:
        db.close()
    char_map = {}

    def _name(cid2):
        if cid2 not in char_map:
            db2 = get_db()
            try:
                c2 = db2.query(Character).filter(Character.id == cid2).one_or_none()
                char_map[cid2] = c2.name if c2 else f"#{cid2}"
            finally:
                db2.close()
        return char_map[cid2]

    out_rels = [
        {"type": r.type, "other": _name(r.target_id), "chapter": r.chapter}
        for r in rels_out
    ]
    in_rels = [
        {"type": r.type, "other": _name(r.source_id), "chapter": r.chapter}
        for r in rels_in
    ]
    return templates.TemplateResponse(
        request=request,
        name="world_character.html",
        context={
            "char": c,
            "appear": appear,
            "out_rels": out_rels,
            "in_rels": in_rels,
        },
    )


@app.get("/self/{num}", response_class=HTMLResponse)
def self_chapter(request: Request, num: int):
    """自家版本阅读页：直接读物化成品（version=self，scripts/materialize_self.py 生成）。

    选稿决策（原文 or 引擎）在内容准备阶段已固化（data/self_decision.json），
    路由只读成品；来源徽标从决策文件读，标题保持原回目名。
    """
    import json

    db = get_db()
    try:
        from ..models import Chapter

        ch = (
            db.query(Chapter)
            .filter(Chapter.version == "self", Chapter.num == num)
            .first()
        )
        all_chs = (
            db.query(Chapter.num, Chapter.title)
            .filter(Chapter.version == "self")
            .order_by(Chapter.num)
            .all()
        )
    finally:
        db.close()
    if ch is None:
        return templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"num": num},
            status_code=404,
        )
    # 来源徽标：从固化决策读
    decision_path = ROOT / "data" / "self_decision.json"
    source_label = "引擎重建"
    if decision_path.exists():
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if decision.get(str(num)) == "original":
            source_label = "癸酉本原文 · 文笔达标"
    prev = next_ = None
    for n, t in all_chs:
        if n == num - 1:
            prev = (n, t)
        elif n == num + 1:
            next_ = (n, t)
    paragraphs = [p for p in ch.content.split("\n") if p.strip()]
    annotated = [render_annotated(p) for p in paragraphs]
    return templates.TemplateResponse(
        request=request,
        name="engine_chapter.html",
        context={
            "chapter": ch,
            "paragraphs": paragraphs,
            "annotated": annotated,
            "all_chapters": all_chs,
            "prev": prev,
            "next": next_,
            "total": len(all_chs),
            "source_label": source_label,
            "base_path": "/self",
        },
    )


@app.get("/engine/{num}", response_class=HTMLResponse)
def engine_chapter(request: Request, num: int):
    """自家版本（引擎重建）阅读页。"""
    db = get_db()
    try:
        from ..models import GeneratedChapter

        ch = (
            db.query(GeneratedChapter)
            .filter(GeneratedChapter.num == num)
            .first()
        )
        all_chs = (
            db.query(GeneratedChapter.num, GeneratedChapter.title)
            .order_by(GeneratedChapter.num)
            .all()
        )
    finally:
        db.close()
    if ch is None:
        return templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"num": num},
            status_code=404,
        )
    prev = next_ = None
    for n, t in all_chs:
        if n == num - 1:
            prev = (n, t)
        elif n == num + 1:
            next_ = (n, t)
    paragraphs = [p for p in ch.content.split("\n") if p.strip()]
    return templates.TemplateResponse(
        request=request,
        name="engine_chapter.html",
        context={
            "chapter": ch,
            "paragraphs": paragraphs,
            "all_chapters": all_chs,
            "prev": prev,
            "next": next_,
            "total": len(all_chs),
            "source_label": "引擎重建",
            "base_path": "/engine",
        },
    )


@app.get("/compare/{num}", response_class=HTMLResponse)
def compare(request: Request, num: int, v: str = ""):
    db = get_db()
    try:
        all_chs = (
            db.query(Chapter.num, Chapter.title)
            .filter(Chapter.version == "zdic")
            .order_by(Chapter.num)
            .all()
        )
        # 版本注册表：所有可选版本（含 OCR 与影印版）
        version_sources = [
            ("gong", "脂评汇校", "gongban", "text"),
            ("zdic", "汉典校订本", "zdic", "text"),
            ("chengjia", "程甲本", "chengjia", "text"),
            ("chengyi", "程乙本", "chengyi", "text"),
            ("chengyi_ocr", "程乙本OCR", "chengyi_ocr", "text"),
            ("hys_ocr", "红研所OCR", "hys_ocr", "text"),
            ("fax_chengyi", "程乙本影印", "chengyi", "fax"),
            ("fax_hys", "红研所影印", "hys_ocr", "fax"),
        ]
    finally:
        db.close()

    # 解析用户选择的版本（默认全部有数据的）
    selected = [x.strip() for x in v.split(",") if x.strip()] if v else []

    # 查各版本是否有本章数据
    db2 = get_db()
    try:

        def has_chapter(ver: str, n: int) -> bool:
            return (
                db2.query(Chapter)
                .filter(Chapter.version == ver, Chapter.num == n)
                .first()
                is not None
            )

        available = []
        for key, label, dbv, kind in version_sources:
            if kind == "text" and has_chapter(dbv, num):
                available.append((key, label, dbv, kind))
            elif kind == "fax":
                # 影印版：有对应 OCR 数据则可用
                if has_chapter(dbv, num):
                    available.append((key, label, dbv, kind))
    finally:
        db2.close()

    # 若未指定或指定的无效，默认全选可用版本
    if not selected:
        selected = [k for k, _, _, _ in available]
    else:
        avail_keys = {k for k, _, _, _ in available}
        selected = [k for k in selected if k in avail_keys]

    versions = []
    for key, label, dbv, kind in available:
        if key not in selected:
            continue
        ch = get_db()
        try:
            chapter = (
                ch.query(Chapter)
                .filter(Chapter.version == dbv, Chapter.num == num)
                .first()
            )
        finally:
            ch.close()
        versions.append(
            {
                "key": key,
                "label": label,
                "db": dbv,
                "kind": kind,
                "desc": VERSION_DESC.get(key, ""),
                "chapter": chapter,
            }
        )

    if not versions:
        return templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"num": num},
            status_code=404,
        )
    title = versions[0]["chapter"].title if versions[0]["chapter"] else ""

    # 双栏下拉阅读：每个版本一栏，各自完整内容连续滚动，不做配对对齐
    columns = []
    for idx, ver in enumerate(versions):
        vch = _preferred_chapter(ver["chapter"], num)
        kind = ver["kind"]
        if kind == "fax":
            # 影印版：不渲染段落，标记为影印图栏
            columns.append(
                {
                    "label": ver["label"],
                    "key": ver["key"],
                    "desc": VERSION_DESC.get(ver["key"], "影印扫描页"),
                    "kind": "fax",
                    "paras": [],
                }
            )
        else:
            paras = vch.paragraphs
            columns.append(
                {
                    "label": ver["label"],
                    "key": ver["key"],
                    "desc": VERSION_DESC.get(ver["key"], ""),
                    "kind": "text",
                    "paras": [render_annotated(p) for p in paras],
                }
            )

    total = len(all_chs)
    return templates.TemplateResponse(
        request=request,
        name="compare.html",
        context={
            "num": num,
            "title": title,
            "versions": versions,
            "columns": columns,
            "all_chapters": all_chs,
            "selected": ",".join(selected),
            "prev": num - 1 if num > 1 else None,
            "next": num + 1 if num < total else None,
            "total": total,
        },
    )
