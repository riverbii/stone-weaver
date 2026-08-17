"""多版本逐字对照。

公版区：程甲本（chengjia）/ 程乙本（chengyi）/ 庚辰本系（gengchen）/ 脂评汇校本（gongban）前80回互照。
癸酉本区：guihui（v1）/ guihui_v2（vicalloy）/ guihui_v3（StoneStory）互照。

提供字符级 diff 对齐：把两个版本的正文按 opcodes 拆成对齐 token，
渲染时差异字用高亮标出。

差异判定做归一化：简繁、全角/半角标点、空白 不计为差异；
但展示始终用各版本原文。
"""

from __future__ import annotations

import difflib
import re

try:
    import opencc
except ImportError:  # pragma: no cover
    opencc = None

_converter: "opencc.OpenCC | None" = None


def _t2s() -> "opencc.OpenCC | None":
    global _converter
    if opencc is None:
        return None
    if _converter is None:
        _converter = opencc.OpenCC("t2s")
    return _converter


# 古籍异体字 → 简体正字（opencc 不覆盖，需手动映射）
VARIANT_MAP = {
    "囬": "回",
    "歴": "历",
    "畨": "番",
    "隠": "隐",
    "聼": "听",
    "𦗟": "听",
    "呌": "叫",
    "歩": "步",
    "竒": "奇",
    "説": "说",
    "説": "说",
    "說": "说",
    "書": "书",
    "書": "书",
    "讀": "读",
    "閱": "阅",
    "來": "来",
    "峯": "峰",
    "涼": "凉",
    "裏": "里",
    "搆": "构",
    "稟": "禀",
    "敎": "教",
    "詣": "诣",
    "萬": "万",
    "與": "与",
    "衆": "众",
    "於": "于",
    "𭺜": "瓦",
    "𡶶": "峰",
    "𨚫": "却",
    "𦗟": "听",
    "靑": "青",
    "堦": "阶",
    "慾": "欲",
    "眞": "真",
    "髙": "高",
    "幷": "并",
    "併": "并",
    "閒": "闲",
    "㫖": "旨",
    "𣺌": "渺",
    "𰯌": "膝",
    "𪾶": "睡",
    "盹": "盹",
    "閨": "闺",
    "樁": "桩",
    "牀": "床",
    "檻": "槛",
    "嵗": "岁",
    "歳": "岁",
    "喫": "吃",
    "麪": "面",
    "靣": "面",
    "𠒋": "凶",
    "㨿": "据",
    "㝷": "寻",
    "尋": "寻",
    "厯": "历",
    "廻": "回",
    "逈": "迥",
    "𤨏": "琐",
    "𮪍": "骑",
    "𫝃": "尔",
    "尓": "尔",
    "爾": "尔",
    "猒": "厌",
    "賸": "剩",
    "佉": "去",
    "衞": "卫",
    "衛": "卫",
    "𥞊": "秋",
    "𨗳": "导",
    "𨓬": "过",
    "𣸣": "洁",
    "䒭": "等",
    "晉": "旦",
    "彊": "强",
    "强": "强",
    "壔": "岛",
    "嶮": "险",
    "𫎫": "象",
    "𡈽": "土",
    "籤": "签",
    "籤": "签",
    "際": "际",
    "際": "际",
    "雲": "云",
    "雲": "云",
    "齊": "齐",
    "雲": "云",
    "縂": "总",
    "總": "总",
    "懺": "忏",
    "攺": "改",
    "攺": "改",
    "𥞊": "秋",
    "吆": "甚",
    "𨒛": "逋",
    "弔": "吊",
    "弔": "吊",
    "稲": "稻",
    "穌": "苏",
    "囬": "回",
}

VARIANT_MAP = {k: v for k, v in VARIANT_MAP.items()}


def norm_text(text: str) -> str:
    """归一化文本（等长）：全角标点→半角、繁体→简体、古籍异体字→正字、
    控制/零宽字符去除。

    返回长度与输入一致，保证逐字符对齐。
    """
    out: list[str] = []
    for ch in text:
        o = ord(ch)
        if o == 0x3000 or o in (0x200B, 0x200C, 0x200D, 0xFEFF):
            out.append(" ")
            continue
        if ch in "「」『』“”‘’":
            out.append('"')
            continue
        if 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
            continue
        out.append(ch)
    half = "".join(out)
    conv = _t2s()
    if conv is not None:
        half = conv.convert(half)
    # 古籍异体字兜底 → 正字
    return "".join(VARIANT_MAP.get(ch, ch) for ch in half)


def is_insignificant(ch: str) -> bool:
    """归一化后无意义的字符：空白、零宽、控制符。"""
    return ch.isspace() or ord(ch) < 0x20


ANNOTATION_RE = re.compile(r"〔批(?:[:：][^〕]*)?〕(.*?)〔/批〕", re.S)
V2_ANNOTATION_RE = re.compile(r"【(?:批语|回前批|夹批|批注|注|按)[^】]*】", re.S)
GONGBAN_ANNOTATION_RE = re.compile(
    r"(?:\n|^)(?:甲|庚|蒙|戚|靖|列|己|甲侧|庚侧|蒙侧|戚侧|甲双|庚双|蒙双|戚双|靖藏|列藏|己卯)：[^\n]*",
    re.M,
)


def strip_annotations(text: str) -> str:
    """去掉批注标记（v1 的〔批〕、v2 的【批语】、公版的 甲：/庚： 前缀三种格式），保留正文。

    对行内脂批（甲侧：…。）也剥离，返回纯正文。批注文字替换为空格以保持等长，
    保证 opcodes 索引可直接映射回原文。
    """
    text = ANNOTATION_RE.sub(lambda m: " " * (m.end() - m.start()), text)
    text = V2_ANNOTATION_RE.sub(lambda m: " " * (m.end() - m.start()), text)
    text = GONGBAN_ANNOTATION_RE.sub(lambda m: " " * (m.end() - m.start()), text)
    # 行内脂批：来源前缀 → 句末标点（含引号闭合），替换为空格
    parts = _ANNOT_SRC_RE.split(text)
    out: list[str] = [parts[0]]
    for i in range(1, len(parts), 2):
        src = parts[i]
        rest = parts[i + 1] if i + 1 < len(parts) else ""
        out.append(" " * (len(src) + 1))  # 前缀+冒号
        end_m = re.search(r"[。！？]", rest)
        if end_m:
            content_len = end_m.end()
            while content_len < len(rest) and rest[content_len] in '」』”’"':
                content_len += 1
            out.append(" " * content_len)
            out.append(rest[content_len:])
        else:
            out.append(rest)
    return "".join(out)


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n") if p.strip()]


def char_diff(a: str, b: str) -> list[dict]:
    """字符级 diff，返回对齐 token 序列 [{a, b, tag}]。

    用归一化文本比较；简繁/标点/空白/批注差异视为相等，不产生高亮，
    但 token 中保留原文用于渲染。
    """
    # 批注字符等长替换为空格，使其不参与差异判定
    ba, bb = strip_annotations(a), strip_annotations(b)
    na, nb = norm_text(ba), norm_text(bb)
    sm = difflib.SequenceMatcher(
        lambda ch: is_insignificant(ch), na, nb, autojunk=False
    )
    tokens: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            tokens.append({"a": a[i1:i2], "b": b[j1:j2], "tag": "eq"})
        elif tag == "replace":
            tokens.append({"a": a[i1:i2], "b": b[j1:j2], "tag": "rep"})
        elif tag == "delete":
            tokens.append({"a": a[i1:i2], "b": "", "tag": "del"})
        elif tag == "insert":
            tokens.append({"a": "", "b": b[j1:j2], "tag": "ins"})
    merged: list[dict] = []
    for t in tokens:
        if (
            t["tag"] != "eq"
            and not _is_whitespace_only(t["a"])
            and not _is_whitespace_only(t["b"])
        ):
            merged.append(t)
        else:
            merged.append({"a": t["a"], "b": t["b"], "tag": "eq"})
    out: list[dict] = []
    for t in merged:
        if out and out[-1]["tag"] == "eq" and t["tag"] == "eq":
            out[-1]["a"] += t["a"]
            out[-1]["b"] += t["b"]
        else:
            out.append(dict(t))
    return out


def _is_whitespace_only(s: str) -> bool:
    return s == "" or all(c.isspace() for c in s)


def char_diff_titles(a: str, b: str) -> list[dict]:
    """回目标题 diff：保留空格/分隔符可读，其余字符级。"""
    return char_diff(a, b)


def split_sentences_punct(text: str) -> list[str]:
    """按标点符号切成句子（保留标点）。边界：。！？； 及引号闭合。"""
    out: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "。！？；":
            # 吸收后续引号闭合符
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return [s for s in out if s.strip()]


def _merge_annot_sentences(sentences: list[str]) -> list[str]:
    """把以批注前缀开头的句子并入前一句（批注作为前一句的夹批）。"""
    out: list[str] = []
    for s in sentences:
        if _ANNOT_SRC_RE.match(s.strip()) and out:
            out[-1] += s
        else:
            out.append(s)
    return out


def build_comparison(text_a: str, text_b: str) -> list[dict]:
    """两栏并排阅读：按标点切成句子，句子级字符对齐。

    每行 = 一句（或多句聚合，若两侧句子数不同则按对齐合并）。
    """
    sa = _merge_annot_sentences(split_sentences_punct(text_a))
    sb = split_sentences_punct(text_b)

    # 归一化句子（剥批注 + norm），用于匹配
    na = [norm_text(strip_annotations(s)) for s in sa]
    nb = [norm_text(strip_annotations(s)) for s in sb]

    sm = difflib.SequenceMatcher(None, na, nb, autojunk=False)
    ops = sm.get_opcodes()

    rows: list[dict] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"a": sa[i1 + k], "b": sb[j1 + k]})
        elif tag == "replace":
            a_cnt, b_cnt = i2 - i1, j2 - j1
            n = min(a_cnt, b_cnt)
            for k in range(n):
                rows.append({"a": sa[i1 + k], "b": sb[j1 + k]})
            for k in range(n, a_cnt):
                rows.append({"a": sa[i1 + k], "b": ""})
            for k in range(n, b_cnt):
                rows.append({"a": "", "b": sb[j1 + k]})
        elif tag == "delete":
            for k in range(i2 - i1):
                rows.append({"a": sa[i1 + k], "b": ""})
        elif tag == "insert":
            for k in range(j2 - j1):
                rows.append({"a": "", "b": sb[j1 + k]})

    # 计算差异标记
    for r in rows:
        tokens = char_diff(r["a"], r["b"]) if (r["a"] and r["b"]) else []
        r["same"] = not any(t["tag"] != "eq" for t in tokens)
        r["tokens"] = tokens
    return rows


def _split_by_lines(a: str, b: str) -> list[tuple[str, str]]:
    """把 opcode 的 a/b 片段按共同换行位置切成 (la, lb) 行块。"""
    if "\n" not in a and "\n" not in b:
        return [(a, b)]
    a_lines = a.split("\n")
    b_lines = b.split("\n")
    n = max(len(a_lines), len(b_lines))
    chunks: list[tuple[str, str]] = []
    for i in range(n):
        la = a_lines[i] if i < len(a_lines) else ""
        lb = b_lines[i] if i < len(b_lines) else ""
        chunks.append((la, lb))
    return chunks


VERSIONS = {
    "v1": {"db": "guihui", "label": "库内原版", "has": list(range(1, 109))},
    "v2": {"db": "guihui_v2", "label": "vicalloy整理", "has": list(range(81, 109))},
    "v3": {"db": "guihui_v3", "label": "StoneStory2020", "has": list(range(1, 109))},
}


# ============================================================
# 脂批解析（夹批展示用）
# ============================================================

# 批注来源前缀（含被 43 字换行截断的"甲\n侧："）
ANNOT_SOURCES = {
    "甲侧": "甲",
    "甲眉": "甲",
    "甲夹": "甲",
    "庚侧": "庚",
    "庚眉": "庚",
    "蒙侧": "蒙",
    "蒙双": "蒙",
    "戚夹": "戚",
    "戚序": "戚",
    "戚总评": "戚",
    "靖藏": "靖",
    "列藏": "列",
    "己卯": "己",
}
_ANNOT_SRC_RE = re.compile(
    r"(甲侧|甲眉|甲夹|庚侧|庚眉|蒙侧|蒙双|戚夹|戚序|戚总评|靖藏|列藏|己卯)[:：]"
)
# 截断前缀："甲\n侧：" 中行首是"侧："
_ANNOT_TAIL_RE = re.compile(r"^(?:侧|眉|夹|双|藏|卯|序|总评)：")

# 批注来源 → 展示色（读感：甲=朱砂红，庚=墨青，蒙=黛绿，戚=绛紫，靖=赭，列=蓝灰，己=墨黑）
ANNOT_COLORS = {
    "甲": "var(--ann-jia, #a23a2a)",
    "庚": "var(--ann-geng, #2f6b8f)",
    "蒙": "var(--ann-meng, #3d7a4f)",
    "戚": "var(--ann-qi, #7a4a8f)",
    "靖": "var(--ann-jing, #8a5a2a)",
    "列": "var(--ann-lie, #4a5f7a)",
    "己": "var(--ann-ji, #5a5a5a)",
}


# 癸酉本〔批:color〕…〔/批〕
GUIOU_ANNOT_RE = re.compile(r"〔批(?:[:：]([^〕]*))?〕(.*?)〔/批〕", re.S)


def parse_annotations(text: str) -> list[dict]:
    """把含脂批的原文解析成节点流。

    支持两种格式：
      1. 癸酉本 〔批:red〕…〔/批〕（source=癸，color=red）
      2. 脂评汇校 甲侧：/蒙侧：…（source=甲/蒙/戚…）
    """
    # 若含癸酉本〔批〕格式，先按它解析
    if GUIOU_ANNOT_RE.search(text):
        return _parse_guihui(text)
    return _parse_gongban(text)


def _parse_guihui(text: str) -> list[dict]:
    """解析癸酉本〔批〕格式。"""
    nodes: list[dict] = []
    pos = 0
    for m in GUIOU_ANNOT_RE.finditer(text):
        if m.start() > pos:
            seg = text[pos : m.start()]
            nodes.append({"type": "text", "text": seg})
        color = m.group(1) or "red"
        nodes.append(
            {
                "type": "annot",
                "text": m.group(2).strip(),
                "source": "癸",
                "source_label": "癸酉批",
                "color": color,
            }
        )
        pos = m.end()
    if pos < len(text):
        nodes.append({"type": "text", "text": text[pos:]})
    out: list[dict] = []
    for n in nodes:
        if n["type"] == "text" and out and out[-1]["type"] == "text":
            out[-1]["text"] += n["text"]
        else:
            out.append(n)
    return out


def _parse_gongban(text: str) -> list[dict]:
    """把含脂批的原文解析成节点流。

    返回 [{type: "text"|"annot", text, source?}]。
    批注内容 = 来源前缀后 → 到句末标点（。！？）为止（含后续引号闭合）。
    段落内先合并碎片行，再扫描。
    段首版本来源标记（庚：/戚序：等）不视为批注，去标记保留正文。
    """
    # 段首版本来源标记（庚辰本/戚序本等底本标记）→ 去标记
    text = re.sub(r"^(?:庚|戚序|甲戌|己卯|靖藏|列藏|蒙府|戚|列)：", "", text.strip())
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    merged_lines: list[str] = []
    buf = ""
    for l in lines:
        if not l:
            if buf:
                merged_lines.append(buf)
                buf = ""
            continue
        buf += l
    if buf:
        merged_lines.append(buf)
    body = "\n".join(merged_lines)

    nodes: list[dict] = []
    text_buf = ""
    pos = 0
    for m in _ANNOT_SRC_RE.finditer(body):
        if m.start() > pos:
            text_buf += body[pos : m.start()]
        src_label = m.group(1)
        src = ANNOT_SOURCES.get(src_label, "甲")
        # 批注内容：句末标点（含后续引号闭合）
        rest = body[m.end() :]
        end_m = re.search(r"[。！？]", rest)
        content_end = 0
        if end_m:
            content_end = end_m.end()
            # 吸收紧跟的引号闭合符
            while content_end < len(rest) and rest[content_end] in '」』”’"':
                content_end += 1
            content = rest[:content_end]
        else:
            content = rest
        if text_buf.strip():
            nodes.append({"type": "text", "text": text_buf.strip()})
            text_buf = ""
        nodes.append(
            {
                "type": "annot",
                "text": content.strip(),
                "source": src,
                "source_label": src_label,
            }
        )
        pos = m.end() + (content_end if end_m else 0)
    if pos < len(body):
        text_buf += body[pos:]
    if text_buf.strip():
        nodes.append({"type": "text", "text": text_buf.strip()})

    out: list[dict] = []
    for n in nodes:
        if n["type"] == "text" and out and out[-1]["type"] == "text":
            out[-1]["text"] += n["text"]
        else:
            out.append(n)
    return out


def split_sentences(text: str) -> list[str]:
    """把文本切成句子序列（保留句末标点与夹批）。

    句子边界：。！？； 及引号闭合后的这些标点；批注前缀文字保留在句内。
    """
    out: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "。！？；":
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def align_sentences(sa: list[str], sb: list[str]) -> list[dict]:
    """句子级对齐：返回 [{a, b, same, a_idx, b_idx}]。

    比较用剥批注后的正文归一化文本，避免批注干扰配对。
    """

    def body(s: str) -> str:
        parts = parse_annotations(s)
        return norm_text("".join(p["text"] for p in parts if p["type"] == "text"))

    na = [body(p) for p in sa]
    nb = [body(p) for p in sb]
    sm = difflib.SequenceMatcher(None, na, nb, autojunk=False)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out.append(
                    {
                        "a": sa[i1 + k],
                        "b": sb[j1 + k],
                        "same": True,
                        "a_idx": i1 + k,
                        "b_idx": j1 + k,
                    }
                )
        elif tag == "replace":
            a_cnt, b_cnt = i2 - i1, j2 - j1
            n = min(a_cnt, b_cnt)
            for k in range(n):
                out.append(
                    {
                        "a": sa[i1 + k],
                        "b": sb[j1 + k],
                        "same": False,
                        "a_idx": i1 + k,
                        "b_idx": j1 + k,
                    }
                )
            for k in range(n, a_cnt):
                out.append(
                    {
                        "a": sa[i1 + k],
                        "b": "",
                        "same": False,
                        "a_idx": i1 + k,
                        "b_idx": None,
                    }
                )
            for k in range(n, b_cnt):
                out.append(
                    {
                        "a": "",
                        "b": sb[j1 + k],
                        "same": False,
                        "a_idx": None,
                        "b_idx": j1 + k,
                    }
                )
        elif tag == "delete":
            for k in range(i2 - i1):
                out.append(
                    {
                        "a": sa[i1 + k],
                        "b": "",
                        "same": False,
                        "a_idx": i1 + k,
                        "b_idx": None,
                    }
                )
        elif tag == "insert":
            for k in range(j2 - j1):
                out.append(
                    {
                        "a": "",
                        "b": sb[j1 + k],
                        "same": False,
                        "a_idx": None,
                        "b_idx": j1 + k,
                    }
                )
    return out


def align_version_paragraphs(pa: list[str], pb: list[str], thresh: float = 0.4) -> list[dict]:
    """段落单调最优对齐（DP），返回 [{a, b, same, a_idx, b_idx}].

    保证 A/B 各自全部段落都出现（未匹配侧显示为空），不丢失内容。
    """
    from functools import lru_cache

    def body(s: str) -> str:
        parts = parse_annotations(s)
        return norm_text("".join(p["text"] for p in parts if p["type"] == "text"))

    n, m = len(pa), len(pb)
    ba = [body(p) for p in pa]
    bb = [body(p) for p in pb]

    @lru_cache(maxsize=None)
    def sim(i: int, j: int) -> float:
        # 用"最长公共子串占短段比例"判断对应，比 ratio 宽容（段落边界/长度不同也能匹配）
        a, b = ba[i], bb[j]
        if not a or not b:
            return 0.0
        m = difflib.SequenceMatcher(None, a, b)
        lm = m.find_longest_match(0, len(a), 0, len(b))
        return lm.size / min(len(a), len(b))

    NEG = -1e9
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = 0
    for j in range(m + 1):
        dp[0][j] = 0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = max(
                dp[i - 1][j],
                dp[i][j - 1],
                dp[i - 1][j - 1] + (sim(i - 1, j - 1) - thresh),
            )

    # 回溯路径
    path: list[str] = []  # 记录每步动作
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (sim(i - 1, j - 1) - thresh):
            path.append(("pair", i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j]:
            path.append(("a_only", i - 1))
            i -= 1
        else:
            path.append(("b_only", j - 1))
            j -= 1
    path.reverse()

    out: list[dict] = []
    for act, *idx in path:
        if act == "pair":
            ia, ib = idx
            s = sim(ia, ib)
            out.append({"a": pa[ia], "b": pb[ib], "same": s >= thresh, "a_idx": ia, "b_idx": ib})
        elif act == "a_only":
            ia = idx[0]
            out.append({"a": pa[ia], "b": "", "same": False, "a_idx": ia, "b_idx": None})
        else:
            ib = idx[0]
            out.append({"a": "", "b": pb[ib], "same": False, "a_idx": None, "b_idx": ib})
    return out


def has_diff(tokens: list[dict] | None) -> bool:
    if not tokens:
        return False
    return any(t["tag"] != "eq" for t in tokens)
