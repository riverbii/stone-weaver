# stone-weaver

agentic 叙事引擎——LLM + 知识图谱重建/续写红楼梦。见 `project_stone_weaver.md` 获取项目记忆（grep `^## ` 索引 + partial read，勿全文读）。

## 滚动会话日志（跨会话记忆）

`.opencode/session_log.md` 是本项目**一比一滚动记录**的对话原文（user/assistant 文本，含时间戳），由全局插件 `~/.config/opencode/plugins/session-log.js` 在每次 `session.idle` 时自动增量追加。

新开会话恢复上下文的顺序：
1. 读 `.opencode/session_log.md` **文件尾部**（最新段在底，`Read` 用大 offset / `tail`）
2. 结合 `project_stone_weaver.md` 的项目记忆（grep 索引 + 最近几段）
3. 也可跑 `/wake`

不要把 `.opencode/session_log.md` 当记忆文件改写；它是只读的原文流水，永不编辑。
