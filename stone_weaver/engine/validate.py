"""叙事引擎 · 一致性校验器。

架构定位（docs/architecture.md §5）：
  规则 + LLM 双轨。规则快（存活/在场/地点硬约束），LLM 判断性格口吻。
  校验失败 → 带 violations 反馈重生成（让 LLM 看到错在哪）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..llm import LLMClient
from ..world.state import WorldState

# 状态简报里标记死亡/特殊状态的关键词（从 WorldState.describe 抓）
DEAD_MARKERS = ("已故", "自缢", "病逝", "被杀", "赐死", "身亡", "薨逝", "发配")


@dataclass
class Violation:
    """一条一致性违规。"""

    rule: str  # dead_present / absent_present / style / personality
    message: str
    severity: str = "error"  # error（必改） / warn（建议）


def validate_rules(state: WorldState, events: list[dict]) -> list[Violation]:
    """规则校验：参与事件的已死人物不得在场。

    依据：状态快照里 alive=False 的人物（name 匹配事件 participants）。
    """
    violations: list[Violation] = []
    dead_names = {
        p.name for p in state.persons.values() if not p.alive
    }
    for ev in events:
        for name in ev.get("participants") or []:
            if name in dead_names:
                violations.append(
                    Violation(
                        rule="dead_present",
                        message=f"「{name}」已故（按世界状态），却在事件「{ev.get('summary','')[:20]}」中出场",
                    )
                )
    return violations


def validate_personality(
    client: LLMClient, text: str, state: WorldState
) -> list[Violation]:
    """LLM 校验：人物口吻/性格是否符合其设定（warn 级，供人工参考）。"""
    prompt = (
        "你是红楼梦考据专家。下面是一段续写正文。请检查其中人物言行是否符合原著设定"
        "（如宝玉痴情尊女、黛玉敏感多思、凤姐泼辣机变）。"
        f"\n\n已知世界状态：\n{state.describe(limit=15)}\n\n正文：\n{text[:4000]}"
        "\n\n只输出 JSON 数组，元素 {\"name\": \"人物\", \"issue\": \"问题描述\"}，无问题输出 []。"
    )
    raw = client.chat([{"role": "system", "content": prompt}], temperature=0.0)  # 异常上抛
    import json

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
        Violation(rule="personality", message=f"{d.get('name','?')}：{d.get('issue','')}", severity="warn")
        for d in data
        if isinstance(d, dict) and d.get("issue")
    ]


def feedback_prompt(violations: list[Violation]) -> str:
    """把违规转成重生成反馈（给 LLM 看）。"""
    if not violations:
        return ""
    lines = ["【一致性校验反馈——请修正以下问题后重写】"]
    for v in violations:
        lines.append(f"- [{v.severity}] {v.message}")
    return "\n".join(lines)
