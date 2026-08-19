"""文风引擎 · 风格锚点抽取。

架构定位（docs/architecture.md §6）：
  不做模型微调，用前80回（gongban_rb）做 few-shot 风格锚点 + 输出评估。
  本模块负责从原文抽取代表性段落（对话/描写/章回结构样例）。

锚点类型：
  - dialogue_jiaoyu  宝玉口吻（痴语、女儿论）
  - dialogue_daiyu   黛玉口吻（尖刻、诗性）
  - dialogue_fengjie 凤姐口吻（泼辣、市井）
  - scene_landscape  大观园景致描写
  - scene_emotion    人物心理/情感段落
  - opening          章回开篇句式
  - closing          章回收尾句式
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Chapter

# 批注标记（甲夹/戚序/庚眉…/甲：回前批/〔批…〕…〔/批〕）——锚点不要含批语
_ANNOT_RE = re.compile(
    r"(?:甲侧|甲眉|甲夹|庚侧|庚眉|蒙侧|蒙双|戚夹|戚序|戚总评|靖藏|列藏|己卯)[:：]"
    r"|^[甲乙丙丁戊己庚辛壬癸][:：]"
    r"|〔批(?:[:：][^〕]*)?〕|〔/批〕"
)
# 回前总评特征句（这类是批语不是正文）
_PREFACE_HINTS = ("此回亦非正文", "此回中凡用", "按此回", "回前总评", "此回忽遣", "此回乃", "此回系", "此回写")


def _clean(text: str) -> str:
    # 去掉"甲：xxx。"式的回前批残句（以天干开头且含"此回/本旨"特征）
    t = _ANNOT_RE.sub("", text).strip()
    t = re.sub(r"^[甲乙丙丁戊己庚辛壬癸]：", "", t)
    return t.strip()

# 锚点人物的定位关键词（在段落里出现即算该人物戏份）
CHAR_HINTS = {
    "dialogue_jiaoyu": ("宝玉", "宝二爷"),
    "dialogue_daiyu": ("黛玉", "林妹妹"),
    "dialogue_fengjie": ("凤姐", "凤辣子", "琏二奶奶"),
}


@dataclass
class StyleAnchor:
    """一段风格锚点：类型 + 原文片段 + 用途说明。"""

    kind: str
    text: str
    note: str = ""


def _split_paras(ch: Chapter, max_len: int = 260) -> list[str]:
    out = []
    for p in ch.paragraphs:
        if 40 <= len(p) <= max_len:
            out.append(p)
    return out


def extract_anchors(db: Session, chapters: list[int] | None = None, per_kind: int = 3) -> list[StyleAnchor]:
    """从前80回抽取风格锚点。chapters=None 时用 1-80 全量（抽代表性）。

    策略：按类型扫描，每个类型保留"最典型"的若干段（优先含对话引号/诗句）。
    """
    if chapters is None:
        chapters = list(range(1, 81))
    anchors: dict[str, list[str]] = {k: [] for k in ("dialogue_jiaoyu", "dialogue_daiyu", "dialogue_fengjie", "action_scene", "scene_landscape", "scene_emotion", "opening", "closing")}

    for num in chapters:
        ch = (
            db.query(Chapter)
            .filter(Chapter.version == "gongban_rb", Chapter.num == num)
            .first()
        )
        if ch is None:
            continue
        paras = _split_paras(ch)
        for p in paras:
            if any(h in p for h in _PREFACE_HINTS):
                continue
            for kind, hints in CHAR_HINTS.items():
                if len(anchors[kind]) >= per_kind * 2:
                    continue
                if any(h in p for h in hints) and ("道" in p or "说" in p or "笑" in p or "？" in p):
                    anchors[kind].append(p)
            # 动作交锋段：多动作词 + 有对话（正是"人物互动多"的示范）
            action_verbs = ("起身", "上前", "拉住", "拦住", "扯", "夺", "推", "跪", "摔", "啐", "抢", "夺门", "拽", "一把", "登时", "忙", "便")
            if (
                len(anchors["action_scene"]) < per_kind * 2
                and sum(1 for v in action_verbs if v in p) >= 2
                and ("道" in p or "说" in p or "笑" in p)
                and len(p) < 300
            ):
                anchors["action_scene"].append(p)
            # 场景描写：含"、"列举或方位词且无引号
            if (
                len(anchors["scene_landscape"]) < per_kind * 2
                and '"' not in p
                and "“" not in p
                and any(k in p for k in ("潇湘馆", "怡红院", "大观园", "园中", "廊下", "池边"))
            ):
                anchors["scene_landscape"].append(p)
            if (
                len(anchors["scene_emotion"]) < per_kind
                and any(k in p for k in ("不觉", "心下", "暗自", "越想", "悲", "叹", "痴"))
                and len(p) < 200
            ):
                anchors["scene_emotion"].append(p)
        # 开篇/收尾（每回取首尾段，跳过回前批）
        if paras:
            first, last = paras[0], paras[-1]
            if not any(h in first for h in _PREFACE_HINTS) and len(anchors["opening"]) < per_kind * 2:
                anchors["opening"].append(first)
            if not any(h in last for h in _PREFACE_HINTS) and len(anchors["closing"]) < per_kind * 2:
                anchors["closing"].append(last)

    out: list[StyleAnchor] = []
    for kind, texts in anchors.items():
        for t in texts[:per_kind]:
            cleaned = _clean(t)
            if cleaned:
                out.append(StyleAnchor(kind=kind, text=cleaned))
    return out


def format_anchors(anchors: list[StyleAnchor]) -> str:
    """把锚点拼进文风约束 prompt 的"风格样例"段落。"""
    notes = {
        "dialogue_jiaoyu": "宝玉的说话口吻（痴语、女儿至上）",
        "dialogue_daiyu": "黛玉的说话口吻（机敏、诗性、微带尖刻）",
        "dialogue_fengjie": "凤姐的说话口吻（泼辣爽利、市井机变）",
        "action_scene": "动作+对话交锋（人物互动推进，白描，不抒情）",
        "scene_landscape": "大观园景物描写（工笔白描、四时意象）",
        "scene_emotion": "人物心理与情感段落（含蓄、以景衬情）",
        "opening": "章回开篇（常以诗句/议论起）",
        "closing": "章回收尾（常以悬念/诗收）",
    }
    lines = ["以下为曹雪芹原著的风格样例，请在风格上严格模仿（句式、用词、节奏）："]
    for a in anchors:
        lines.append(f"\n【{notes.get(a.kind, a.kind)}】\n{a.text}")
    return "\n".join(lines)
