#!/usr/bin/env python3
"""别名撞名归并：把"同一人物的不同称谓"合并为一条。

原理（安全规则，只处理无歧义的）：
  - 若 A.name 出现在 B.aliases 里，且 B.name 出现在 A.aliases 里 → A、B 互认，明确同人
  - 若 B 的名字是 A 的"全名+姓氏"形式（如 宝玉 vs 贾宝玉 / 湘云 vs 史湘云），
    且全名版不含歧义 → 合并到全名版
  - 不自动处理：渺渺真人/跛足道人 这类有红学争议的（需人工）
  - 不自动处理：太太/老爷/老太太 这类泛称（多义，需人工）

用法:
  .venv/bin/python scripts/merge_aliases.py            # 只报告
  .venv/bin/python scripts/merge_aliases.py --apply    # 应用合并
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stone_weaver.ingest.text import make_session
from stone_weaver.models import Character

# 泛称（多义，绝不自动合并）
GENERIC = {"太太", "老爷", "老太太", "奶奶", "姑娘", "小姐", "和尚", "道人", "道士", "婆子", "丫鬟", "妈妈", "嬷嬷", "老婆子", "舅舅", "哥哥", "姐姐", "妹妹", "二姑娘", "三姑娘", "四姑娘", "大姐姐", "二哥哥", "二奶奶", "云姑娘", "探丫头", "蕉丫头", "四丫头", "姨奶奶", "姨妈", "大奶奶", "嫂子", "大嫂子", "珍大嫂子"}

# 有争议的（人工判定）
SKIP_PAIRS = {("渺渺真人", "跛足道人")}

# 同名不同人（绝不合并；名字本身作为切断点）
# 甄宝玉 vs 贾宝玉：金陵甄家宝玉是独立人物
HARD_SEPARATE = {
    "甄宝玉",  # 与 宝玉/贾宝玉 不同人
    "薛二姑娘", "甄家二姑娘", "甄家三姑娘",  # 与 迎春/探春 不同人（薛宝琴/甄家姑娘）
}

# 亲属称谓型（"X之母/X之妻/X之父"——应挂到主人物别名，不是同人组合并）
KINSHIP_SUFFIX = ("之母", "之妻", "之父", "之子", "之女", "之祖", "之孙", "之叔", "之兄", "之弟", "之姐", "之妹", "嫡妻")
# 称谓词尾（含这些结尾的别名不作为"同人"证据——太泛，会串链不同人物，如"大奶奶"把李纨和尤氏串起来）
TITLE_SUFFIX = ("奶奶", "太太", "夫人", "姑娘", "小姐", "嫂子", "媳妇", "家的", "老爷", "少爷", "哥儿", "姐姐", "妹妹", "姨娘", "嬷嬷", "妈妈", "婶子", "姑妈", "姨妈", "大爷", "大嫂子", "婶婶", "哥哥", "兄弟", "大哥", "大叔", "老大", "阿呆", "氏")


def find_groups(db) -> list[list[Character]]:
    """找出同人组。

    规则（单向别名即可，比双向互认更全面）：
      - B.name 出现在 A.aliases 里，或 B.name 是 A 的全名（贾+宝玉），
        且 B 不是泛称/硬分离/亲属称谓 → B 并入 A 组
      - 传递：A 组的成员 C 如果又指向别人，一并纳入
    """
    chars = db.query(Character).all()
    by_name = {c.name: c for c in chars}
    alias_map = {
        c.name: {
            a for a in (c.aliases or [])
            if len(a) > 1
            and a not in HARD_SEPARATE
            and not any(a.endswith(k) for k in KINSHIP_SUFFIX)
            and not any(a.endswith(k) for k in TITLE_SUFFIX)
        }
        for c in chars
    }
    groups: list[list[Character]] = []
    seen: set[int] = set()
    for c in chars:
        if (
            c.id in seen
            or c.name in GENERIC
            or len(c.name) <= 1
            or c.name in HARD_SEPARATE
            or any(c.name.endswith(k) for k in KINSHIP_SUFFIX)
        ):
            continue
        # 收集与 c 同人的所有人物（单向：c 的别名指向谁，或谁指向 c）
        members = [c]
        stack = [c]
        while stack:
            cur = stack.pop()
            cur_aliases = alias_map.get(cur.name, set())
            # 1) cur 的别名里有 other → other 并入
            for other_name, other in by_name.items():
                if (
                    other.id in seen
                    or other.name in GENERIC
                    or other.name in HARD_SEPARATE
                    or other.name in KINSHIP_SUFFIX
                    or any(other.name.endswith(k) for k in KINSHIP_SUFFIX)
                    or any(other.name.endswith(k) for k in TITLE_SUFFIX)
                    or len(other.name) <= 1
                ):
                    continue
                pointed = other.name in cur_aliases
                full_form = (
                    other.name.startswith(cur.name[:1])
                    and other.name.endswith(cur.name)
                    and len(other.name) > len(cur.name)
                    and cur.name not in GENERIC
                    and cur.name[0] in SURNAMES
                ) or (
                    cur.name.startswith(other.name[:1])
                    and cur.name.endswith(other.name)
                    and len(cur.name) > len(other.name)
                    and other_name not in GENERIC
                    and other.name[0] in SURNAMES
                )
                if pointed or full_form:
                    if other.id not in seen:
                        members.append(other)
                        seen.add(other.id)
                        stack.append(other)
            # 2) 别人的别名里有 cur → 那人并入
            for other_name, other in by_name.items():
                if (
                    other.id in seen
                    or other.name in GENERIC
                    or other.name in HARD_SEPARATE
                    or any(other.name.endswith(k) for k in KINSHIP_SUFFIX)
                    or any(other.name.endswith(k) for k in TITLE_SUFFIX)
                ):
                    continue
                if cur.name in alias_map.get(other_name, set()):
                    if other.id not in seen:
                        members.append(other)
                        seen.add(other.id)
                        stack.append(other)
        if len(members) > 1:
            # 去重（同一个人可能经多条路径加入）
            seen_ids = set()
            uniq = []
            for mem in members:
                if mem.id not in seen_ids:
                    seen_ids.add(mem.id)
                    uniq.append(mem)
            groups.append(uniq)
        seen.add(c.id)
    return groups


def report(db) -> list[str]:
    lines = []
    for g in find_groups(db):
        names = [c.name for c in g]
        lines.append(f"[同人组] {' / '.join(names)}")
    return lines


# 姓氏前缀（canonical 优先选带姓氏的标准全名，如 林黛玉 > 黛玉 > 潇湘妃子）
SURNAMES = "贾王史薛林秦尤邢李赵钱孙周吴郑冯陈蒋沈韩杨朱许何吕施张甄花"


def _canonical_rank(c: Character) -> int:
    """canonical 优先级。

    规则：
      - 带姓氏 2 字（林黛玉/李纨）= 0
      - 带姓氏 3 字（李宫裁/林红玉）= 1
      - **称谓全称 3 字（赵姨娘/X奶奶）应优于其 2 字简称（赵姨）** → 归入 1
      - 带姓氏长名 = 2
      - 不带姓氏 2 字（黛玉/宝玉）= 3
      - 别号（潇湘妃子/怡红公子）= 4
    """
    name = c.name
    if name[0] in SURNAMES and len(name) == 2:
        # 2 字简称（赵姨/李纨）：李纨是真名 OK；但"赵姨"是"赵姨娘"的简称，应让位
        if any(name.endswith(k) for k in ("姨", "奶", "婶")):
            return 2  # 简称称谓让位于 3 字全称
        return 0
    if name[0] in SURNAMES and len(name) == 3:
        return 1  # 赵姨娘/李宫裁/林红玉（3 字全称含称谓）
    if name[0] in SURNAMES:
        return 2
    if len(name) == 2 and name not in GENERIC:
        return 3
    return 4


def apply(db) -> int:
    """合并同人组：保留一个 canonical（优先带姓氏标准全名），其余并入其 aliases 并删除。

    额外清理：单字人物（钗/玉/宝/黛）若别名唯一指向某标准名，并入该标准名。
    """
    # 1) 单字噪音清理
    singles = db.query(Character).filter(Character.kind == "story").all()
    for c in singles:
        if len(c.name) > 1:
            continue
        al = [a for a in (c.aliases or []) if len(a) > 1]
        if len(al) == 1:
            target = db.query(Character).filter(Character.name == al[0]).first()
            if target is not None and target.id != c.id:
                t_aliases = list(target.aliases or [])
                if c.name not in t_aliases:
                    t_aliases.append(c.name)
                target.aliases = t_aliases
                db.delete(c)
    db.commit()

    # 2) 同人组合并
    groups = find_groups(db)
    merged = 0
    for g in groups:
        # canonical：按姓氏全名 > 常用名 > 别号 排序
        g_sorted = sorted(g, key=lambda c: (_canonical_rank(c), -len(c.name)))
        main = g_sorted[0]
        others = g_sorted[1:]
        main_aliases = list(main.aliases or [])
        main_first = main.first_chapter
        for o in others:
            for a in [o.name] + (o.aliases or []):
                a = (a or "").strip()
                if a and a != main.name and a not in main_aliases and a not in GENERIC:
                    main_aliases.append(a)
            if o.first_chapter and (main_first is None or o.first_chapter < main_first):
                main_first = o.first_chapter
            if o.summary and not main.summary:
                main.summary = o.summary
            db.delete(o)
            merged += 1
        main.aliases = main_aliases
        main.first_chapter = main_first
    db.commit()
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default="data/db/stone.db")
    args = ap.parse_args()

    db = make_session(args.db)
    if args.apply:
        n = apply(db)
        print(f"✅ 合并完成：{n} 条重复人物并入 canonical")
        total = db.query(Character).count()
        print(f"   characters 表现存: {total}")
    else:
        lines = report(db)
        print(f"发现 {len(lines)} 个同人组：")
        for l in lines:
            print(" ", l)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
