# adapters/

宿主适配器目录。内核（`core/`、`recall/`、`store/`、`app/`）与宿主无关；每个宿主在这里有一个适配器。

## 现有适配器

| 文件 / 目录 | 宿主 | 语言 | 接入方式 |
|---|---|---|---|
| `astrbot_actions.py` `astrbot_hooks.py` `astrbot_model.py` `astrbot_plugin.py` `astrbot_runtime.py` `seekmemory_context.py` | AstrBot | Python | 同进程，作为 `astrbot.api` 插件加载 |
| `dsh/` | DeepSeek Harness（DSH） | Node ESM（JavaScript） | 跨进程：本机 loopback JSON 契约 |

AstrBot 是默认宿主与参考实现；`dsh/` 是第二个宿主，存在的意义是验证"内核是否真的宿主无关"——它跑在完全不同的语言与进程模型上。

## 共同契约

两个适配器都只依赖 `app/ports.py` 的八个协议：

`ChatModel`、`Retriever`、`SourceStore`、`ArtifactStore`、`ArtifactCache`、`MetricsStore`、`LedgerStore`、`ExtractionStore`

它们都不 import 内核内部实现，也都不修改内核代码。宿主提供端口，内核提供语义。

## 新增一个宿主

1. 先读 `docs/INTERFACES.md` 与 `app/ports.py`；
2. 跨进程的场景按 issue [#107](https://github.com/NeverENG/SeekMemory/issues/107) 的方向：`ChatRequest` / `ChatResponse` 就是线格式，并由宿主拉活，内核不回调宿主；
3. 在 `adapters/<host>/` 下实现，不要改 `core/`、`recall/`、`store/`；
4. 用黑盒用例验收：所有适配器必须能过同一套用例，而不改动用例本身。

## 目录说明

- `astrbot_*.py`：AstrBot 的插件入口、钩子、模型桥与管理页注册；
- `seekmemory_context.py`：AstrBot 侧的上下文组装；
- `dsh/`：DSH 适配器，自带 `README.md`、`package.json`、`dsh.plugin.json`、mock 内核与测试套件。

## 归属

`dsh/` 与本目录其余文件同级维护，是仓库内适配器，不是第三方包。细节见 [`dsh/README.md`](dsh/README.md) 的「归属」一节。
