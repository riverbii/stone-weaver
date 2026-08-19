# stone-weaver 项目记忆

> 按 memory_protocol：追加式（TAIL·新段在底），section 用 `## `，读侧 grep 索引 + partial read。

## [2026-08-13 初建] 项目意图与架构
- 目标：agentic 叙事引擎——用 LLM + 知识图谱重建/续写红楼梦，人物当对象、情节当有向图，基于癸酉本情节版或自定义故事弧。
- 里程碑：先产出"癸酉情节版红楼梦"（公版前80回锁世界模型+文风，癸酉本情节补后28回），交付 PDF 或 Web 阅读器。
- 决策：**不用程高本后40回**（文风/价值观污染前80回世界模型）。**只用癸酉本情节弧，不用盗版原文**。
- 技术栈：Python 3.14 + SQLAlchemy + SQLite（`data/db/stone.db`），FastAPI 备选 web。
- 骨架模块：`models.py`（Chapter/Character/Relationship/Location/Event）、`ingest/text.py`（txt 按"第N回"切分入库）、`world/extract.py`（LLM 提人物）、`cli.py`（ingest/stats）。

## [2026-08-13 首跑] 汇校本入库成功（管道验证通过）
- 来源：`data/红楼梦/石头记(八十回)+红楼梦脂评汇校本.pdf`（576页，全文 220 万字符含脂批）——**唯一有文本层的 PDF**，其余 20+ PDF 全是扫描影印件（无文本层，需 OCR）。
- 清洗：预处理器 `/tmp/prep_huijiao.py` 截掉靖本批语附录（"现将批语作为附录编入"起）+ 删 80 行目录 + 折叠正文回目标题。产物 `data/text/huijiao.txt`（2.9万行）。
- 入库：80 回、75.7 万字、version=gongban → `data/db/stone.db`。
- **管道修的 3 个 bug**：
  1. `pyproject.toml` hatchling 缺 `[tool.hatch.build.targets.wheel] packages` → 装不了依赖（已加 `["stone_weaver"]`）
  2. `stone_weaver/ingest/text.py:8` 相对导入 `from .models` 应为 `from ..models`（模块加载失败）
  3. `stone_weaver/cli.py` 缺 `if __name__ == "__main__"` → `python -m` 静默不执行
- 环境：`.venv`（pip install -e ".[dev]"）。

## [2026-08-13 调研] 癸酉本后28回情节梗概（已有详细资料）
- 子代理已从知乎专栏（"三生三世"连续梗概 / "落拓居主"逐回系列）+ 百度知道概述，交叉核实拿到 **第81-108回完整情节梗概**，未编造。
- 关键情节点：元春上战场被诬赐死；贾环弑父刺死贾政；黛玉主持大观园保卫战→误杀小红→自缢柳叶渚槐树（白骨宝玉安葬）；宝钗劝谏未果→秋千传情改嫁贾雨村→发配病逝雪中；宝玉弃家乞讨、与湘云（沦为乞丐）湘江重逢白头、投海归太虚幻境；情榜108人（宝玉情不情/黛玉情情/宝钗无情）；通灵玉归青埂峰。程高本全无：狱神庙、妙玉瓜洲被掳、凤姐还魂扫雪拾玉、袭人配蒋玉菡等。
- 完整性缺口：81-95、99-104 回仅有综述无逐回细节（知乎系列其余篇被风控）。已存调研报告在会话上下文，未落盘为文件（如需可写 `docs/guihui_plot.md`）。

## [2026-08-13 环境] 命令搬移（opencode）
- 用户要求把 `~/.claude/commands/` 的 chain/fps/retro/wake 搬到 opencode，**原文件未动**，opencode 版本在 `~/.config/opencode/commands/`：
  - `chain.md`/`fps.md`：原样转格式（纯认知框架无损）
  - `retro.md`：CLAUDE.md 检查兼容 AGENTS.md
  - `wake.md`：**重写**——记忆源改为 opencode 的 SQLite 会话库（`~/.local/share/opencode/opencode.db`，查当前项目最近会话+最后文本），memory 按 `project_*.md` grep 索引，全程只读，HUD ≤15 行
- 注意：配置不热加载，重启后生效。
- 用户补充：`~/.config/opencode/commands/` 下 **chain.md / commit.md / explain.md / fps.md 是用户自己写的**（不是 opencode 自带/模板），其余 retro/wake（搬移）、review/test（默认）非用户原创。

## [2026-08-13 用户偏好] 已做过的事不反复做
- **明确指令**："类似这种做过的事情不要反复做了"——已调研过/已解决/已落盘的事，重启后直接复用已有成果（memory / 文档 / 数据库），**不得重跑调研、重查、重做**，除非有新的需求或数据。
- 遵守方式：做任何"调研/查证/实现"前，先 grep memory + 项目文件确认是否已有成果；有则直接引用并报告位置，不重新执行。

## [2026-08-13 完成] 癸酉本情节摘要落盘
- 已将癸酉本后28回情节弧摘要固化到 `docs/guihui_plot.md`（从 memory 摘要导出，标注了完整性缺口 81-95/99-104 回无逐回细节）。

## [2026-08-13 待办] 下一步候选
- 后28回逐回细节补全（重试知乎"落拓居主"系列其余篇，或用户买纸质版后自行 OCR）——**已有摘要见 docs/guihui_plot.md**
- 人物提取跑通（`world/extract.py`，LLM 需要 opencode Go API key 配置）
- Web 阅读器骨架（用户已表态"阅读器只是形式，不是本质"，优先级应低于内容/引擎本身）
- 其余 PDF OCR 管道（如需其他版本文本）

## [2026-08-14] 公版对照页（多栏阅读）重大进展
- **对照页改为多栏并排下拉阅读**（不做逐行 diff 对齐），每版本一栏独立滚动、同步滚动。
- **版本数据**：
  - `gongban_rb`：脂评汇校 80回（从 gongban 43字碎片重构为语义段落，含脂批夹批；页眉噪音已清除）
  - `zdic`：汉典校订本 120回（1982人文社校注本，前80回庚辰底本/后40回程甲底本，无脂批），来源 gj.zdic.net/jibu/961/（URL 连续 31559-31678，第n回=31558+n）
  - `chengjia`：程甲本（维基文库，**仅 ch1-2**，其余被 IP 限流未抓）
- **展示**：对照页 3栏（脂评汇校|汉典|程甲 ch1-2），每栏头部版本说明（VERSION_DESC），120回导航下拉+上一回/下一回，夹批小字按来源分色。
- **关键修复**：build_static.py compare 页原只导出1-108 → 改为1-120（否则 ch109-120 线上 404）。
- **脚本**：`scripts/fetch_zdic.py`（汉典，URL编号推导回数）、`scripts/rebuild_zdic.py`（zdic按句末标点统一分段~200字/段）、`scripts/fetch_chengjia_slow.py`（维基文库程甲慢速断点续传，抗限流）、`scripts/rebuild_paras.py`（gongban语义重构）。
- **版本说明**：脂评汇校=庚辰本系为主参校诸脂本含脂批；汉典=1982人文社校注本（前80庚辰/后40程甲底本，无脂批）；程甲=1791程伟元/高鹗活字本120回。
- **未完成**：程甲 ch3-80（维基文库限流，后台慢速抓取已暂停待下次）、程乙本（ctext需翻页复杂）、庚辰本（脂评汇校已覆盖庚辰系）。
- **数据源要点**：维基文库是唯一纯程甲源但按 IP 限流（间歇窗口）；ctext.org 是程乙系需翻页；汉典是混合整理本。

## [2026-08-14 待办] 下次继续
- 维基文库限流解除后，用 `fetch_chengjia_slow.py` 抓程甲 ch3-80（断点续传，从 ch3 开始）
- 决定是否补程乙本（ctext 翻页方案）或接受"脂评汇校+汉典+程甲"三版本
- 对照页前端细节可继续调（栏宽、移动端、夹批样式）

## [2026-08-17 规划] 转攻引擎主线 + 路线图落盘
- **用户拍板 3 决策**：①认可转攻引擎（阅读器只承接，程甲降级后台慢抓/放弃）②LLM 用 opencode Zen 网关 ③图谱原料=公版前80回（gongban_rb）优先。
- **路线图已落盘** `docs/roadmap.md`（阶段0-4，每阶段可验收）：
  - 0 收尾（LLM 链路+试点）→ 1 世界模型（人物/关系/地点/事件四表，1-2周）→ 2 文风锁定+叙事引擎原型（单回生成+校验闭环）→ 3 后28回重建（从 guihui_v3 全文提取情节弧，**无需再调研**）→ 4 整合呈现（门户"自家版本"卡片实装）。
- **LLM 链路打通**：`data/.env`（gitignore 内）写入 opencode Zen 网关 key（来源 `~/.local/share/opencode/auth.json` 的 opencode-go 条目）；`llm.py` 增加 load_dotenv 加载。
- **试点结论（第1回）**：提取质量好；但 **网关长文本不稳定**——6000+ 字符偶发空响应/500，≤3000 稳定 → 提取策略=按 ~2000-3000 字分段 + 指数退避重试；80 回全量约 3-4 小时可后台跑。
- 修 bug：`world/extract.py` EXTRACT_PROMPT.format() 被 JSON 花括号破坏 → 改 .replace()。
- 规则兜底（rule_based_mentions）噪音大，仅辅助。

## [2026-08-17 待办] 下一步（阶段1启动）
- 世界模型批量提取：写批量脚本（分段+重试+断点续传），先跑公版前80回人物 → 再关系/地点/事件
- 图谱浏览/统计页（"谁在第几回见了谁"）作为验收物
- 同名归并（宝玉=宝二爷=绛洞花主）抽查
- 程甲本决定：放弃 or 后台慢抓

## [2026-08-17 阶段1启动] 世界模型构建
- **提取脚本 4 个就绪**（scripts/ 下）：
  - `extract_characters.py` 人物（分段~2200字+指数退避重试+断点续传 progress_*.txt）
  - `extract_relationships.py` 关系（依赖人物表）
  - `extract_locations.py` 地点（独立）
  - `extract_events.py` 事件=情节有向图节点（依赖人物表）
  - `merge_characters.py` 别名归并分析/应用
- **kind 维度**：人物分 story（故事人物）/reference（典故引用），**ch2 正邪二气论 40+ 历史人物已正确归 reference**（红拂/紫烟/曹雪芹/脂砚斋等）；ch1 story=17/ref=14，ch2 story=26/ref=3。
- **图谱页上线**（本地验证 OK，待部署）：
  - `/world` 人物图谱（kind 过滤、统计）
  - `/world/chapter/{1-80}` 单回出场人物（别名规则匹配提及次数）
  - `/world/character/{id}` 人物档案（关系、出场回分布 chips）
  - 门户首页加"世界模型"卡片；build_static.py 导出 world 页（前80回）
- **归并待办**：英莲=甄英莲（明确同人）、贾雨村嫡妻→并入别名（规则可自动）；渺渺真人/跛足道人关系有争议需人工（红学中跛足道人=渺渺真人凡间化身说法不一）。
- **进度**：全量 80 回人物提取后台跑（bash-7），约 6-7 小时；跑完后依次跑关系/地点/事件，再做归并+部署。

## [2026-08-17 架构落地] 叙事引擎骨架完成
- **架构设计文档** `docs/architecture.md`：分层（L0数据/L1知识/L2情节/L3生成/L4呈现）+ 世界状态 + 情节弧 + 主循环 + 文风引擎。
- **已实现**（全链路 import 通过，核心已测）：
  - models.py +4 表：character_states（人物动态状态）/event_edges（情节图边）/arcs（情节弧）/generated_chapters（引擎产出）
  - `world/state.py`：state_at/apply_event/describe（190 人物快照测试通过）
  - `engine/arc.py`：Beat/Arc 模型、save/load 往返通过
  - `engine/generate.py`：plan→generate→extract 三件套
  - `engine/validate.py`：规则校验（已死人物不得出场）+ LLM 性格校验
  - `engine/simulate.py`：主循环 simulate_one_beat（带违规反馈重生成）
  - `style/anchors.py`：7 类风格锚点 + 批语清洗（回前批/夹批/〔批〕全过滤）
  - `style/style.py`：文风 prompt 组装；`style/assess.py`：自动评估（句长/过渡词/语气词/现代词）
  - scripts：build_arc.py / trial_generate.py / generate_chapters.py
- **另一 AI 的工作**：OCR 文本处理（程乙 OCR、影印数据、回目定位）——L0 数据层，与引擎层无冲突，chapters 表汇合。
- **重要修复**：LLM 429/5xx 原被各提取函数 `except Exception: return []` 吞掉 → 静默产出空回（ch23-40 全 0 人）。已改 llm.py 内置指数退避重试 + 各函数异常上抛。**ch23-40 需重跑**（进度已重置到 ch22）。
- **限流教训**：提取与试点并发会抢网关配额触发 429；大批量任务应串行、避免并发调用。

## [2026-08-17 方向扩展] 前80回统一版 + 世界模型迁移
- **用户新决策**：不只写后28回，**前80回也要基于各版本做一个统一版**（汇校：脂评汇校/汉典/程甲/程乙/OCR 等），统一版做好后**世界模型应建立在统一版之上**（"应该先做统一版再做世界模型，不过你做了就做了，等做好再改"）。
- **当前世界模型底本**：`gongban_rb`（脂评汇校·语义重构版，前80回，庚辰系）——已提取 301 人（ch1-22 有效，ch23-40 因 429 bug 待重跑）。
- **迁移要求**：世界模型管线必须**底本可配置**——统一版入库后（如 version=unified）一键重跑，不改代码。
- **现状差距**：人物提取已参数化（--version）；**关系/地点/事件脚本 + web world 页硬编码 gongban_rb，需参数化**。
- **待办**：① 参数化 3 个提取脚本 + world 页 ② 用户统一版就绪后全量重跑世界模型（清空旧数据）③ 风格锚点也切到统一版。

## [2026-08-17 草稿标注] 世界模型 = draft（基于 gongban_rb）
- 用户确认：**统一版未做**（另一 AI 无 token），当前世界模型是**草稿**，底本 gongban_rb。
- 数据层已加 `characters.source_version` 列，现有 342 人标记 `gongban_rb`；提取脚本 save_characters 已支持写入。
- 迁移：统一版入库为 version=unified → 4 个提取脚本 --version unified 全量重跑（source_version 区分草稿/正式）。
- 网关限流已恢复，提取重启跑 ch23-80（bash-17），修复后不再空回（ch23 +8 / ch24 +23）。

## [2026-08-17 阶段2试点] 文风生成首次成功 ✅
- **最小试点通过**（沁芳桥畔·宝玉黛玉闲谈场景）：自动评估 **0.62 分（文风达标）**。
- 生成质量：章回体腔调自然（"话说这一日""款款走来"）、葬花情节无缝衔接原著、人物口吻区分（宝玉痴语/黛玉尖刻）、结尾化用《葬花吟》诗句收束。
- 修复：生成输出清洗残留标记（`<｜end▁of▁sentence｜>`）→ style.py `_clean_output`。
- 验证链路：anchors 抽取 → style prompt 组装 → generate_scene → assess 自动评估，全通。
- 注意：试点与提取并发会加剧网关限流；**大批量任务严格串行**。

## [2026-08-18 归并事故与修复] 别名归并 canonical 选择 bug
- **事故**：merge_aliases.py 初版 canonical 选"名字最长者"→ 黛玉组 canonical 变成"潇湘妃子"，林黛玉等标准名记录被删（897→778 但核心人物丢失）。
- **处理**：清空 characters + 重置进度 + DeepSeek 重跑全量 80 回（约 40 分钟）。
- **修复**：canonical 优先"带姓氏标准全名"（林黛玉>黛玉>潇湘妃子）；单向别名指向即可入组（比双向互认全面）；排除 ≤1 字别名（"玉"会串起所有含玉人物）、泛称（太太/老爷/二姑娘…）、硬分离名（甄宝玉≠宝玉，薛二姑娘≠迎春）、亲属称谓（X之母/X之妻）。
- **教训**：归并类破坏性操作先跑模拟数据测试（tests/ 应有 test_merge_aliases.py）；先备份 DB（sqlite .backup）再 apply。
- **当前**：DeepSeek 官方 API 快且稳（每回 25-40s，80 回约 40 分钟）——已替换耗尽的 opencode Zen。

## [2026-08-18 提取管线双 bug 修复]
- **Bug1**：RELATION/LOCATION/EVENT/BEAT/PLANNER 等 prompt 模板用 `{{ }}`（.format 转义符）但替换时未还原 → 模型看到 `{{"source"...}}` 返回空。修复：替换时 `.replace("{{","{").replace("}}","}")`。加了回归测试 test_prompts_have_no_double_braces。
- **Bug2**：共享 `parse_json_list` 过滤 `d.get("name")`，把关系（source/target）事件（summary）全滤成空。修复：parse_json_list 不过滤字段，由调用方决定（人物提取处补 name 过滤）。
- 关系提取验证通过（第3回 4 条：林如海-贾雨村 上下级等）。

## [2026-08-19 阶段1完成] 世界模型全量 + 80→81 衔接点
- **四表全量**（gongban_rb 草稿底本，DeepSeek 官方 API）：人物 876 / 关系 1128 / 地点 412 / 事件 1967。
- **80→81 衔接点就绪**：`build_ch80_state.py` LLM 核查 51 条 ch80 状态快照（9 已故：秦可卿/贾瑞/金钏/尤二姐/尤三姐/晴雯/秦钟/林如海/贾敬；黛玉病重潇湘馆、凤姐病重荣国府、宝玉怡红院）。
- 修复：initial_state_from_events 规则版太粗糙（关键词误伤/漏标）→ 改用 LLM 核查脚本（一次调用）；人物匹配支持别名。
- **阶段2 输入齐备**：人工情节弧(arc id=1) + ch80 世界状态 + 文风锚点 + 引擎骨架。
