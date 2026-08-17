from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from ..llm import LLMClient
from ..models import Character

SURNAMES = "贾王史薛林秦尤邢李赵钱孙周吴郑冯陈蒋沈韩杨朱许何吕施张"

EXTRACT_PROMPT = """你是红楼梦研究助手。下面是一段原文。请提取其中出现的所有人物及信息。

要求：只输出 JSON 数组，不要其他文字。每个元素格式：
{"name": "标准姓名", "aliases": ["别名"], "gender": "男/女/未知", "clan": "姓或氏族", "house": "归属府邸(如 荣国府/大观园/宁国府)，未知则留空", "kind": "story 或 reference", "summary": "本段体现的身份或特征简述"}

kind 规则：
- story = 红楼梦故事中的真实人物（有台词/戏份/实际出现在场景中，或作为本故事成员被正式介绍，如林黛玉、贾雨村、甄士隐、贾府众丫鬟）
- reference = 仅被提及引用的典故/历史/神话人物（不在本故事中活动，如尧舜禹、曹操、唐寅、女娲氏、空空道人等开篇神话人物，除非后续有持续戏份）
如不确定，宁归 reference。

如无新人物，输出 []。

原文：
{text}
"""


def extract_characters_from_text(client: LLMClient, text: str) -> list[dict]:
    messages = [
        {"role": "system", "content": EXTRACT_PROMPT.replace("{text}", text[:6000])}
    ]
    raw = client.chat(messages, temperature=0.1)  # 异常向上抛，由调用方重试
    return parse_json_list(raw)


def parse_json_list(raw: str) -> list[dict]:
    """容错解析 LLM 返回的 JSON 数组（容忍 ```json 围栏、前后杂文）。"""
    s = raw.strip()
    fence = s.find("```")
    if fence != -1:
        # 取第一个 [ 到最后一个 ]
        a, b = s.find("["), s.rfind("]")
        if a != -1 and b > a:
            s = s[a : b + 1]
    try:
        data = json.loads(s)
    except Exception:
        a, b = s.find("["), s.rfind("]")
        if a == -1 or b <= a:
            return []
        try:
            data = json.loads(s[a : b + 1])
        except Exception:
            return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("name")]


def rule_based_mentions(text: str) -> list[tuple[str, int]]:
    """规则兜底：统计"X+"与"X家的"等明显指人的高频姓氏词。返回 [(词, 次数)]。"""
    counts: dict[str, int] = {}
    for surname in SURNAMES:
        for m in re.finditer(rf"{surname}[^\s，。；、：""''!?]{1,3}", text):
            word = m.group(0)
            counts[word] = counts.get(word, 0) + 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:50]


def names_variants(chars: list[Character]) -> dict[int, list[str]]:
    """人物 id → 匹配词表（标准名 + 别名，去重、去 ≤1 字符、去常见非人名词）。"""
    STOP = {"和尚", "道人", "丫鬟", "小姐", "太太", "老爷", "奶奶", "姑娘", "嬷嬷"}
    out: dict[int, list[str]] = {}
    for c in chars:
        words = {c.name} | set(c.aliases or [])
        words = {w.strip() for w in words if w.strip() and len(w.strip()) > 1}
        words -= STOP
        if words:
            out[c.id] = sorted(words)
    return out


def chapter_mentions(db: Session, chapter_text: str) -> dict[int, int]:
    """计算一段文本里各人物的提及次数（规则匹配，别名展开）。

    返回 {character_id: count}。用于"谁在第几回出场"的快速索引。
    """
    chars = db.query(Character).all()
    variants = names_variants(chars)
    counts: dict[int, int] = {}
    for cid, words in variants.items():
        n = sum(chapter_text.count(w) for w in words)
        if n:
            counts[cid] = n
    return counts


def save_characters(
    db: Session, chars: list[dict], source_version: str | None = None
) -> int:
    """按标准名 upsert：已有则合并别名/补字段，不覆盖已有信息。

    kind 合并规则：story 优先（同一人物某段判 reference、某段判 story，取 story）。
    返回新增人物数。
    """
    added = 0
    for c in chars:
        name = c["name"].strip()
        if not name:
            continue
        exists = db.query(Character).filter(Character.name == name).first()
        kind = "story" if c.get("kind") == "story" else "reference"
        if exists:
            # 合并别名（去重、去空、去同名字）
            cur = list(exists.aliases or [])
            for a in c.get("aliases") or []:
                a = (a or "").strip()
                if a and a != name and a not in cur:
                    cur.append(a)
            exists.aliases = cur
            if kind == "story":
                exists.kind = "story"
            if source_version and not exists.source_version:
                exists.source_version = source_version
            if c.get("gender") and not exists.gender:
                exists.gender = c["gender"]
            if c.get("clan") and not exists.clan:
                exists.clan = c["clan"]
            if c.get("house") and not exists.house:
                exists.house = c["house"]
            if c.get("summary") and not exists.summary:
                exists.summary = c["summary"]
            continue
        db.add(
            Character(
                name=name,
                aliases=c.get("aliases") or [],
                gender=c.get("gender") or None,
                clan=c.get("clan") or None,
                house=c.get("house") or None,
                kind=kind,
                source_version=source_version,
                summary=c.get("summary") or None,
            )
        )
        added += 1
    db.commit()
    return added


RELATION_PROMPT = """你是红楼梦研究助手。下面是第{chapter}回原文片段。请提取其中出现的人物**关系**。

要求：只输出 JSON 数组，不要其他文字。每个元素格式：
{{"source": "关系发起方标准姓名", "target": "关系接受方标准姓名", "type": "关系类型", "detail": "出处简述"}}

关系类型用：父子/母子/夫妻/兄弟/姐妹/主仆/朋友/姻亲/仇敌/师生/上下级/同辈/祖孙 等。
只提取本段明确体现的关系，不要推测。如无，输出 []。

原文：
{text}
"""


def extract_relationships_from_text(
    client: LLMClient, text: str, chapter: int
) -> list[dict]:
    messages = [
        {
            "role": "system",
            "content": RELATION_PROMPT.replace("{text}", text[:6000]).replace(
                "{chapter}", str(chapter)
            ),
        }
    ]
    raw = client.chat(messages, temperature=0.1)  # 异常向上抛，由调用方重试
    return parse_json_list(raw)


def save_relationships(db: Session, rels: list[dict], chapter: int) -> int:
    """按 (source, target, type) 去重 upsert，记录出处回目。返回新增数。"""
    from ..models import Relationship

    added = 0
    for r in rels:
        s_name = (r.get("source") or "").strip()
        t_name = (r.get("target") or "").strip()
        rtype = (r.get("type") or "").strip()
        if not s_name or not t_name or not rtype or s_name == t_name:
            continue
        s = (
            db.query(Character).filter(Character.name == s_name).first()
            or db.query(Character).filter(Character.aliases.contains(s_name)).first()
        )
        t = (
            db.query(Character).filter(Character.name == t_name).first()
            or db.query(Character).filter(Character.aliases.contains(t_name)).first()
        )
        if s is None or t is None:
            continue  # 人物未入库则跳过（等人物全量后再跑）
        exists = (
            db.query(Relationship)
            .filter(
                Relationship.source_id == s.id,
                Relationship.target_id == t.id,
                Relationship.type == rtype,
            )
            .first()
        )
        if exists:
            if exists.chapter is None or chapter < exists.chapter:
                exists.chapter = chapter
            if r.get("detail") and not exists.detail:
                exists.detail = r["detail"]
            continue
        db.add(
            Relationship(
                source_id=s.id,
                target_id=t.id,
                type=rtype,
                chapter=chapter,
                detail=r.get("detail"),
            )
        )
        added += 1
    db.commit()
    return added
