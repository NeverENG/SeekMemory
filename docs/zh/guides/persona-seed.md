# 人格种子文件

Persona seed 是作者提供的初始配置，用于启动唯一的 bot:self Persona Artifact 链。它不是 Source、聊天证据或第二套运行时 profile。seed 文件的纯校验和映射在 core/persona.py，管理侧写入由 ManagementService.bootstrap_persona 完成。

## JSON 格式

必需字段为 id、version、name、persona。其他字段可以省略：

    {
      "id": "big_fish",
      "version": "1.0.0",
      "name": "大肥鱼",
      "persona": "你是大肥鱼，说话温柔但有点嘴硬。",
      "style": {"tone": "温柔嘴硬", "sentence_length": "short"},
      "boundaries": ["不伪造用户经历", "不输出私人 Source 原文"],
      "corpus": [],
      "license": "CC0-1.0",
      "source": "original",
      "content_rating": "general",
      "locale": "zh-CN"
    }

校验规则：

- id 为 2–64 个小写字母、数字、点、下划线或短横线，且首字符是字母或数字。
- version 必须非空，最多 32 字符；name 最多 80 字符；persona 最多 20,000 字符。
- persona_text 是兼容早期 seed 文件的别名，新文件请使用 persona。
- style 是可 JSON 序列化对象，最多 20,000 字符。boundaries 最多 32 项，每项最多 300 字符。
- corpus 可省略；提供时至少 12 组 user/assistant 对话、总正文至少 1,200 字，最多 128 组；单条最多 2,000 字，总 JSON 不超过 50,000 字。每项只允许 user 与 assistant 字段。
- 未知字段会拒绝，避免静默接收无定义数据。

有效示例：[persona.big_fish.json](../../examples/persona.big_fish.json)、[persona.tsundere_ojou.json](../../examples/persona.tsundere_ojou.json)。省略 corpus 时直接提供可用 persona 文本即可。

## 先校验，再写入

从仓库根目录执行：

    python3 scripts/bootstrap_persona.py --db /path/to/memory.db --file docs/examples/persona.big_fish.json --dry-run
    python3 scripts/bootstrap_persona.py --db /path/to/memory.db --file docs/examples/persona.big_fish.json

dry-run 只校验并打印 seed ID、version、corpus 数量和 persona 字数，不打开数据库写入。正式写入会建立或修订同一条 persona Artifact，写入 seed provenance，并在一个 commit_many 事务中整理重复的 active persona 头。

seed 初始头部被标记为 subject_id=bot:self、scope=shared、shareable=public、said_by=seed。初始化不创建 Source、不触发抽取，也不调用模型。若提供 corpus，它会保存在一次性 bootstrap revision 作为作者来源材料；后续演化保留 corpus_count/hash，不把 corpus 注入聊天召回或作为 raw evidence。

## 后续演化与回滚

周期维护只用当前 persona、合格的共享自我印象和有界共享记忆摘要作为综合输入。原始私密 Source 不作为模型输入；一次 Dream 至多进行一项有界 Persona 综合。新内容在相同 Persona ID 上形成追加 revision，并附上证据来源；文本无变化或调用失败时保留现有版本。

管理页可按修订历史回滚。回滚是以历史内容创建的新版本，旧版本不会被覆盖或删除。不要通过编辑另建 Persona Artifact 来形成并行人格链。
