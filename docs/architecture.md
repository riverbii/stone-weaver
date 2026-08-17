# stone-weaver 叙事引擎架构设计

> 版本：v0.1（2026-08-17）
> 定位：本文档是**本质层**设计——agentic 叙事引擎（人物当对象、情节当有向图、LLM 重建/续写）。
> 形式层（阅读器/对照页/图谱页）已有实现，只做承接，不在本文档展开。

## 1. 目标回顾

里程碑产物：**癸酉情节版红楼梦** = 公版前80回（锁世界模型+文风）＋癸酉本情节补后28回（引擎重建）。

**2026-08-17 方向扩展（用户决策）**：
- 不只写后28回——**前80回也基于各版本做一个统一版**（汇校：脂评汇校/汉典/程甲/程乙/OCR 等）。
- **世界模型应建立在统一版之上**（当前临时用 `gongban_rb`，统一版就绪后全量重跑迁移）。
- 迁移要求：世界模型管线**底本可配置**（`--version` 参数，统一版如 `unified`），一键重跑不改代码。

引擎三层本质能力：
1. **世界模型**（静态知识）：人物/关系/地点/事件图谱 ← 阶段1（进行中）
2. **文风引擎**（前80回锁定风格）：生成文本像曹雪芹 ← 阶段2
3. **叙事引擎**（动态推演）：世界状态 + 情节弧 → 生成下一步 → 更新状态 → 校验 ← 阶段2-3

## 2. 总体架构（分层）

```
┌─────────────────────────────────────────────────────┐
│ L4 呈现层（已有）                                     │
│   阅读器 / 对照页 / 图谱页 / 门户                      │
├─────────────────────────────────────────────────────┤
│ L3 生成层（阶段2-3）                                  │
│   文风引擎 style/     叙事生成器 engine/generate.py    │
│   一致性校验 engine/validate.py                       │
├─────────────────────────────────────────────────────┤
│ L2 情节层（阶段1-3）                                  │
│   情节弧 engine/arc.py    情节图 engine/plotgraph.py   │
│   世界状态机 world/state.py                           │
├─────────────────────────────────────────────────────┤
│ L1 知识层（阶段1，进行中）                             │
│   characters / relationships / locations / events     │
│   world/extract.py 批量提取管线                        │
├─────────────────────────────────────────────────────┤
│ L0 数据层（已有）                                     │
│   chapters 多版本原文（gongban_rb 80 / zdic 120 /      │
│   chengyi 80 / chengyi_ocr / guihui_v3 108 …）        │
└─────────────────────────────────────────────────────┘
```

数据流（阶段3 主循环）：

```
前80回世界状态快照 ──┐
                    ├──> 后28回情节弧(guihui_v3 提取)
癸酉本108回全文 ─────┘            │
                                  ▼
   世界状态 WorldState ──> 情节弧 next beat ──> LLM 生成下一步
         ▲                                      │
         │                                      ▼
   校验 + 状态更新 <────── 事件提取/情节图落库 <──┘
```

## 3. 世界模型层（L1 + L2 的状态部分）

### 3.1 人物 = 对象（静态 + 动态）

现有 `characters` 表是**静态档案**。人物对象还需**动态状态**（叙事引擎的最小单元）：

```
CharacterState:
  character_id  → 人物档案（静态属性：姓名/别名/氏族/归属/性格）
  chapter       → 该状态所属回目
  alive         → 是否在世（黛玉自缢后 = False）
  location      → 当前位置（大观园/狱神庙/瓜洲/雪中…）
  status        → 特殊状态（出家/发配/病重/被掳/流落街头…）
  note          → 状态变更说明（来源事件）
```

- **存储**：`character_states` 表，每回生成后写入一份快照（只写变化的回，未变不重复）。
- **查询**：`WHERE character_id=? AND chapter<=? ORDER BY chapter DESC LIMIT 1` 取某回时的状态。
- **用途**：① 生成器输入（"现在谁活着、谁在哪"）② 校验器依据（"此人已死/不在场，不能出场"）③ **80→81 衔接的关键**——阶段1 结束时从 `events` 推导前80回末状态快照。

### 3.2 情节图 = 事件节点 + 有向边

现有 `events` 表是"每回一串事件"（平铺）。升级为**有向图**：

- **节点**：`events`（已有字段够用：chapter_id/seq/summary/participants/location）
- **边**：新增 `event_edges` 表

```
event_edges:
  from_event_id → 因事件
  to_event_id   → 果事件
  kind          → causal(因果) / temporal(时序) / conflict(冲突)
  note          → 边说明（如"黛玉误杀小红 → 黛玉自缢"）
```

- 边由 LLM 在事件提取时一并产出（同一次调用，不额外成本）。
- 后28回重建时，情节弧 beat 之间的因果关系即图的骨架。

### 3.3 世界状态 WorldState

聚合视图：`{characters 动态状态 + 情节图当前节点 + 未决情节线索}`。
- 实现为 `world/state.py` 的内存对象 + 快照落库，不另建表。
- 提供两个纯函数（可测）：
  - `initial_state_from_events(db, chapter=80) -> WorldState`（阶段1 收尾时做）
  - `apply_event(state, event) -> (new_state, violations)`（校验与推进合一）

## 4. 情节弧（engine/arc.py）

**定义**：高层目标序列，是叙事引擎的"剧本"。

```
Arc:
  id / name / version(guihui_v3)
  beats: [Beat, ...]          # 有序目标
Beat:
  scene         → 场景（"柳叶渚槐树下"）
  goal          → 本 beat 目标（"黛玉误杀小红后自缢"）
  characters    → 核心人物
  constraints   → 约束（"须在元春死后/贾府败落背景下"）
  expected_out  → 预期结果（用于校验生成是否达标）
```

**来源**（阶段3 第一步，无需再调研）：
- 从 `guihui_v3`（108回全文，已入库）逐回用 LLM 压缩为 beat——`scripts/build_arc.py`
- 产出后人工抽查，修正明显偏差，固化为 `arcs` 表 + `docs/guihui_arc.md` 可读版

## 5. 叙事引擎主循环（engine/simulate.py）

核心是**窄闭环**（阶段2 先做单 beat，验证质量再扩展）：

```
def simulate_one_beat(state, beat, style) -> (new_state, chapter_text, events, violations):
    1. plan  = planner(state, beat)        # LLM：把 beat 展开为场景计划（人物/地点/动作序列）
    2. text  = generator(state, plan, style) # LLM：按公版文风生成章回文本（分段 few-shot）
    3. evs   = extractor(text)             # LLM/规则：从文本回提事件（含因果边）
    4. (new_state, violations) = apply_event(state, evs)   # 校验+更新
    5. if violations 不可接受: 回到 2（最多 N 次重生成）
    6. 落库：events + event_edges + character_states + generated_chapters
```

**关键设计决策**：

| 决策 | 选择 | 理由 |
|---|---|---|
| 生成粒度 | **事件/场景级**，不一次生成整回 | 网关长文本不稳定（试点实测 6000+ 字符空响应/500）；分段生成后拼装 |
| 文风基准 | **公版前80回**，癸酉本只作情节骨架 | 癸酉本文风与公版差异大；用户决策"前80回锁文风" |
| 一致性校验 | **规则 + LLM 双轨** | 规则快（存活/在场/地点）；LLM 判断性格口吻 |
| 重生成策略 | 校验失败 → 带 violations 反馈重生成 | 让 LLM 看到错在哪，比冷重试质量高 |
| 世界状态来源 | 事件驱动（apply_event 推导），不手动维护 | 单一路径，避免状态与文本漂移 |

## 6. 文风引擎（style/）

**不做模型微调**（数据/成本不允许），用 **prompt 级 few-shot + 输出评估**：

```
style/anchors.py  从前80回抽取风格锚点：
                  - 对话片段（宝玉/黛玉/凤姐口吻差异）
                  - 场景描写段落（大观园景致）
                  - 章回起承转合结构样例
style/style.py    组装文风约束 prompt + 评估
style/assess.py   轻量自动评估：输出 vs 前80回
                  - 用词分布 top-N 重叠率
                  - 句子长度分布
                  - 虚词/语气词频率（"了/呢/罢"）
                  人工终审为准
```

## 7. 数据模型扩展（models.py 增补）

```
新表：
  character_states  人物动态状态快照（见 §3.1）
  event_edges       情节图边（见 §3.2）
  arcs              情节弧（beats JSON）
  generated_chapters 引擎产出回目（version='engine_xxx', arc_id, 状态: draft/reviewed）
```

```python
class CharacterState(Base):
    __tablename__ = "character_states"
    id, character_id(FK), chapter(int), alive(bool),
    location(str|None), status(str|None), note(str|None)
    __table_args__ = (UniqueConstraint("character_id", "chapter"),)

class EventEdge(Base):
    __tablename__ = "event_edges"
    id, from_event_id(FK), to_event_id(FK),
    kind(str: causal/temporal/conflict), note(str|None)

class Arc(Base):
    __tablename__ = "arcs"
    id, name, version, beats(JSON), source_chapter_range(str)

class GeneratedChapter(Base):
    __tablename__ = "generated_chapters"
    id, arc_id(FK), num(int), title, content(Text),
    status(str: draft/reviewed), review_note(str|None)
```

## 8. 模块划分与实现顺序

```
stone_weaver/
  models.py            # schema 扩展（§7）
  llm.py               # 已有
  world/
    extract.py         # 已有（人物/关系/事件提取）
    state.py           # ✅ NEW: WorldState / CharacterState 查询与快照
  engine/
    arc.py             # ✅ NEW: 情节弧模型 + 从 guihui_v3 提取
    plotgraph.py       # 情节图（事件 + 边）读写（部分并入 simulate._persist）
    generate.py        # ✅ NEW: 场景/章回生成器（分段 few-shot）
    validate.py        # ✅ NEW: 一致性校验（规则 + LLM）
    simulate.py        # ✅ NEW: 主循环（§5）
  style/
    anchors.py         # ✅ NEW: 风格锚点抽取（7 类，批语清洗）
    style.py           # ✅ NEW: 文风 prompt 组装
    assess.py          # ✅ NEW: 文风评估（句长/过渡词/语气词/现代词）
  web/                 # 已有（呈现层，只加"自家版本"入口）
scripts/
  build_arc.py         # ✅ NEW: guihui_v3 → 后28回情节弧
  generate_chapters.py # 驱动引擎逐回生成（待写）
```

**实现状态（2026-08-17）**：
- ✅ models.py 4 新表已建（character_states/event_edges/arcs/generated_chapters）
- ✅ world/state.py：state_at/apply_event/describe 已测（190 人物快照、黛玉死亡示例通过）
- ✅ engine/arc.py：Beat/Arc 模型、save/load 往返已测
- ✅ style/anchors.py：7 类锚点抽取 + 批语清洗（回前批/夹批/〔批〕全过滤）
- ✅ style/assess.py：能区分公版原文(0.42) vs 现代白话(0.33)
- ✅ engine/generate.py + validate.py + simulate.py：全链路 import 通过，待接 LLM 实跑
- ✅ **底本参数化**：4 个提取脚本 + web world 页均支持 `--version`/`?version=`（统一版就绪后切 `unified` 一键重跑）
- ⏳ 人物提取后台等待网关限流恢复（bash-17，ch23-40 待重跑）
- ⏳ 待办：`scripts/generate_chapters.py` 驱动脚本、后28回 build_arc 实跑、阶段2 单 beat 试点

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 文风不像（最致命） | few-shot 锚点 + 评估指标 + 人工抽查；不行就加"原文改写"任务（给公版段落让模型模仿改写）热身 |
| 人物一致性漂移 | 状态快照硬约束（规则校验拦截）+ violations 反馈重生成 |
| 后28回情节与癸酉本出入 | 情节弧 beat 做硬目标（expected_out 校验），生成自由度在"怎么写"而非"写什么" |
| 80→81 世界状态不准 | 阶段1 收尾专门做前80回状态快照推导 + 人工抽查关键人物（宝玉/黛玉/凤姐/贾母） |
| 生成成本 | 分段生成 + 失败重试上限；试点后估算单回成本再全量 |

## 10. 与另一个 AI 的工作边界

- 另一 AI：OCR 文本处理（程乙 OCR、影印数据、回目定位）——**L0 数据层补充**，只影响"版本更多"，不影响引擎架构。
- 本架构：L1-L3 引擎层。两者在 `chapters` 表汇合，无代码冲突面（模块不同）。

## 待确认问题（与用户对齐）

1. 情节弧来源：直接用 guihui_v3 逐回压缩（快，含癸酉本文风杂质）还是先人工整理梗概再补细节（准，慢）？建议前者 + 人工抽查。
2. 生成范围：阶段2 先做**前80回内单回仿写**（验证文风，无情节压力）还是直接后28回首回（81）？建议先仿写试水温。
3. 文风评估权重：自动指标 vs 人工判断，各占多少？
