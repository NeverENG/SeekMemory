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

## 带封面的人格包

旧版纯设定 JSON 继续可用，不需要迁移。可移植完整包使用 `.seekmemory.json`，外层格式如下；`seed` 沿用上面的规范，不向 Persona Artifact 添加图片字段。

```json
{
  "format": "seekmemory.persona-pack/v1",
  "seed": {"id": "my-persona", "version": "1", "name": "示例", "persona": "作者编写的设定", "license": "CC0-1.0", "source": "original"},
  "licenseText": "覆盖设定与封面的完整许可证正文",
  "artwork": null
}
```

有封面时，`artwork` 为 `{"mediaType":"image/png","dataBase64":"…"}`，不接受文件路径或远程地址。完整包不超过 3 MiB，设定不超过 64 KiB，许可证 UTF-8 不超过 64 KiB。封面不超过 2 MiB、单边 2048 像素且总像素不超过 400 万；仅支持静态、8 位、非交错 PNG。校验签名、数据块校验和、像素解压长度及行过滤器，去掉附属元数据；其他图片请先导出为此格式。

带封面时，seed 中的 license/source 和 licenseText 都必须非空。许可证必须覆盖包中图片。校验不会替代作者对权利和内容的审核。

在“我的包”导入旧 JSON 或完整包后，可以添加/替换封面、填写许可证，再确认保存蓝图。导入不会自动安装；安装另需明确确认。预览可分别导出纯设定和完整包。完整包不包含原始 Source、证据或运行状态；人格正文仍需分享者自行检查。

本地文件继续保存在 `persona_packs/<id>.json`；内容可以是旧 seed，也可以是新外层格式。更新须带旧版本号和不同的新版本号，先保存旧文件到 `.trash`，再原子发布完整新文件；移除也只移入 `.trash`，当前人格不变。恢复可重新导入备份。回退旧代码前先导出纯设定 JSON；旧代码无法读取新外层格式，但数据库及已安装人格不受影响。

内置包仍采用 `persona_seeds/<id>/persona.json`、`LICENSE`，可选 `artwork.png`。将资源加入 Git 后，打包脚本会校验并包含它们。不支持的资源、损坏/空/超大图片及符号链接会阻止打包。没有封面或读取失败时，界面显示名称首字占位。
