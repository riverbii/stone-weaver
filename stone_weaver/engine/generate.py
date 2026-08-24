"""叙事引擎 · 场景生成与事件回提。

架构定位（docs/architecture.md §5）：
  simulate 循环的第 1-3 步：
    plan  = planner(state, beat)     # LLM：beat → 场景计划
    text  = generator(state, plan, style)  # 文风生成
    evs   = extractor(text)          # 从生成文本回提事件（含因果边）
"""

from __future__ import annotations

from ..llm import LLMClient
from ..style.anchors import StyleAnchor
from ..style.style import generate_scene
from ..world.state import WorldState

PLANNER_PROMPT = """你是红楼梦叙事设计专家。给定一个叙事节拍（beat）和当前世界状态，请把 beat 展开为具体的场景计划。

只输出 JSON 对象：
{{"scenes": [{{"order": 1, "where": "地点", "who": ["在场人物"], "what": "本场景发生的事（含动作与对话要点）"}}], "note": "场景衔接说明"}}

规则：
- 每个场景只写"发生什么"，不要写文风（文风由生成器负责）
- who 只放世界状态中在场/存活的人物
- 2-4 个场景构成一个完整 beat

【世界状态】
{world_state}

【叙事节拍】
{beat}

只输出 JSON，不要其他文字。
"""


def plan_beat(
    client: LLMClient, beat: dict, state: WorldState
) -> list[dict] | None:
    """beat → 场景计划（scenes 列表）。JSON 解析失败返回 None，网络/HTTP 异常上抛。"""
    import json

    prompt = (
        PLANNER_PROMPT.replace("{{", "{")
        .replace("}}", "}")
        .replace("{world_state}", state.describe())
        .replace("{beat}", json.dumps(beat, ensure_ascii=False))
    )
    raw = client.chat([{"role": "system", "content": prompt}], temperature=0.3)  # 异常上抛
    s = raw.strip()
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b <= a:
        return None
    try:
        data = json.loads(s[a : b + 1])
    except Exception:
        return None
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list):
        return None
    return [sc for sc in scenes if isinstance(sc, dict) and sc.get("what")]


EXTRACT_EVENT_PROMPT = """你是红楼梦研究助手。下面是刚生成的一段小说正文。请提取其中发生的**事件**（按时间顺序）。

只输出 JSON 数组，每个元素：
{{"summary": "谁做了什么（一句话）", "participants": ["人物姓名"], "location": "地点，未知留空", "cause_of": "该事件导致了后面哪个事件的序号（无则0）"}}

规则：
- 事件粒度：一个连续动作为一个事件
- participants 用正文中的姓名/称谓
- cause_of 填本数组中事件的序号（1-based），表示因果边
如无事件，输出 []。

正文：
{text}
"""


def extract_events_from_text(client: LLMClient, text: str) -> list[dict]:
    """从生成文本回提事件（含因果边信息）。JSON 解析失败返回 []，HTTP 异常上抛。"""
    import json

    prompt = (
        EXTRACT_EVENT_PROMPT.replace("{{", "{")
        .replace("}}", "}")
        .replace("{text}", text[:6000])
    )
    raw = client.chat([{"role": "system", "content": prompt}], temperature=0.1)  # 异常上抛
    s = raw.strip()
    a, b = s.find("["), s.rfind("]")
    if a == -1 or b <= a:
        return []
    try:
        data = json.loads(s[a : b + 1])
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [
        d
        for d in data
        if isinstance(d, dict) and d.get("summary")
    ]


def generate_and_extract(
    client: LLMClient,
    beat: dict,
    state: WorldState,
    anchors: list[StyleAnchor],
) -> tuple[str, list[dict]]:
    """完整一步：plan → generate → extract。返回 (正文, 事件列表)。

    优先按 beat.points（细粒度情节点，从真实文本提取）逐个生成；
    无 points 时回退 plan_beat 让 LLM 自行规划场景。
    连续生成：每段传入上一段结尾作衔接，避免每段都"话说"另起炉灶。
    """
    points = beat.get("points") or []
    feedback = beat.get("_feedback") or ""
    chunks = []
    if points:
        prev_tail = ""
        for i, pt in enumerate(points, 1):
            goal = f"情节{i}：在{pt.get('scene', '某处')}，{pt.get('goal', '')}"
            chunk = generate_scene(client, goal, state, anchors, prev_tail=prev_tail, feedback=feedback)
            if chunk:
                chunks.append(chunk)
                prev_tail = chunk[-80:]  # 上一段结尾作衔接
    else:
        scenes = plan_beat(client, beat, state)
        if scenes:
            prev_tail = ""
            for sc in scenes:
                goal = f"场景{sc.get('order', '?')}：在{sc.get('where', '某处')}，{sc.get('what', '')}"
                chunk = generate_scene(client, goal, state, anchors, prev_tail=prev_tail, feedback=feedback)
                if chunk:
                    chunks.append(chunk)
                    prev_tail = chunk[-80:]
    text = "\n".join(chunks)
    if not text:
        return "", []
    evs = extract_events_from_text(client, text)
    return text, evs


TIYU_PROMPT = """你是红楼梦续书的开篇诗作者。请为本章写一首"题曰"开篇诗（仿癸酉本风格）。

癸酉本各回"题曰"示例（开篇诗，置于正文"话说"之前，概括本章情节）：
- 「天降良缘贵似金，春风暖样醉好音。」（写喜事）
- 「萧萧落叶皆陈迹，错认红尘堪痛惜。」（写衰败）
- 「傲骨冰清不染尘，孤魂无泪对旧人。」（写黛玉还魂）

【本章情节要点】
{points}

【本章回目】
{title}

要求：
1. 七言两句（一联）为主，可扩展为四句，需押韵、对仗工整
2. 内容**必须贴合本章情节**：从要点中提炼意象与情绪（喜事/丧事/抄家/离别/还魂等）
3. 含蓄用典，不直白（如写抄家用"诏令如山镇微臣"，写离别用"王孙情重思秦晋"）
4. 不是打油诗，用词要有古意
5. 只输出诗句本身（可含"题曰："前缀），不要解释

输出：
"""


def generate_tiyu(client: LLMClient, beat: dict, title: str = "") -> str:
    """为本章生成"题曰"开篇诗。失败返回空字符串。"""
    points = beat.get("points") or []
    point_lines = "\n".join(
        f"- {p.get('scene', '')}: {p.get('goal', '')[:40]}" for p in points[:6]
    ) or beat.get("goal", "")
    prompt = (
        TIYU_PROMPT.replace("{points}", point_lines[:800])
        .replace("{title}", title)
    )
    try:
        raw = client.chat([{"role": "system", "content": prompt}], temperature=0.7)
        return raw.strip()
    except Exception:
        return ""