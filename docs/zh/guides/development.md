# 开发环境与验证

本页提供仓库当前的本地开发入口。协作、分支、worktree 和交付约定见 [CONTRIBUTING.md](../../../CONTRIBUTING.md) 与 [.agents/skills/seekmemory-dev/SKILL.md](../../../.agents/skills/seekmemory-dev/SKILL.md)。

## 环境

- 后端：Python 3.10 或更新版本。
- 管理界面：Node.js 26 与 pnpm 10。
- 根目录 requirements-dev.txt 只用于开发和契约验证，不是插件运行依赖。

在仓库根目录安装契约测试依赖：

    python3 -m pip install -r requirements-dev.txt

## 文档站点

文档站点使用 Material for MkDocs，并通过独立的 requirements-docs.txt 管理依赖。本地构建使用 Python 3.10 或更新版本；CI 使用 Python 3.12。

在仓库根目录安装文档依赖：

    python3 -m pip install -r requirements-docs.txt

启动本地预览（默认地址为 http://127.0.0.1:8000）：

    mkdocs serve

执行严格构建：

    python3 scripts/check_docs_structure.py
    mkdocs build --strict

结构检查验证导航、双语页面集合及相对 Markdown 文件链接；严格构建检查站点能否按当前配置生成。两者不自动验证文档描述是否符合代码。若缺少 `material` 主题，先安装上述文档依赖，不能把依赖缺失当作文档已经通过构建。

## 后端验证层

脚本依据 tests/layers.py 把平铺的 unittest 文件分层，显式 `_unit.py`、`_integration.py` 等后缀优先于旧名称规则。每个文件在独立进程中通过 unittest 发现执行，包含 `__main__` 之后的测试定义，宿主替身不会在文件间传播；全部文件执行后，任一失败均使脚本返回失败。旧文件仍可能跨模块，层名不保证所有依赖完全隔离。按改动选择适当范围：

    python3 scripts/run_tests.py --layer unit
    python3 scripts/run_tests.py --layer contract
    python3 scripts/run_tests.py --layer conformance
    python3 scripts/run_tests.py --layer integration
    python3 scripts/run_tests.py --layer host
    python3 scripts/run_tests.py --layer smoke
    python3 scripts/run_tests.py --layer all

也可在一个进程中发现全部文件；宿主替身可能影响同进程中的可选宿主测试，宿主验收应使用上面的独立进程入口：

    python3 -m unittest discover -s tests -p 'test_*.py' -q

按能力选择 core 检查时，参见 [core 验证入口与证据范围](../architecture/modules/core.md#core-verification)：其中列出现有测试及定向命令，并区分纯规则和完整流程。接口导出检查不等于所有导出操作的完整行为覆盖。

测试不会自动证明真实模型的抽取质量，也不会在没有 AstrBot 的环境里证明宿主行为。跑分与测试的测量范围不同；固定记忆回归会以同一评测器和冻结基线检查逐题退化，失败返回非零；历史综合分不作验收，BM25 另有冻结验收。字数也不等同于 token 或费用；具体定义和限制见 [benchmarks/README.md](../../../benchmarks/README.md)。

## 离线脚本与产物

`scripts/snapshot_db.py` 创建包含 WAL 的一致备份，关闭连接后才原子发布，失败保留原备份；不能把源数据库当作目标。人格初始化、待处理迁移和关系回滚脚本在自身作用域关闭存储。运行服务创建者负责关闭监听端口，保存启动信息失败也会清理。

`benchmarks/run.py`、规模及消融的常规输出位于新的忽略运行目录，不覆盖历史报告。发布打包只是本地产物构建，不代表发布或部署授权。

## 管理界面

    cd dashboard
    pnpm install --frozen-lockfile
    pnpm dev

本地预览默认监听 127.0.0.1:5176。Mock 数据只在浏览器内存中，刷新后清空，不连接真实数据库。

    pnpm check
    pnpm build

check 包含类型生成检查、TypeScript、lint、前端测试和格式检查；build 生成 pages/memory/ 生产页面，该构建产物不提交 Git。更完整说明见 [dashboard/README.md](../../../dashboard/README.md)。

## 修改管理 API

1. 先修改仓库根目录 openapi.yaml。
2. 在 dashboard 中运行 pnpm generate:api，提交生成的 src/contracts/generated.ts；不要手改生成文件。
3. 同步后端路由、管理服务、Zod 运行时校验与契约样本。
4. 执行后端 contract 层及 dashboard 契约验证。具体命令见 dashboard/README.md 的“接口契约与类型生成”。

## 修改架构或文档

- 修改数据语义时，同步更新对应的 core、store、perceive、recall 或 maintain 模块页。
- 修改事件路径、服务组合或宿主边界时，更新架构总览和对应模块页。
- 文档只描述已由当前代码确认的行为；工作计划和 review 记录留在 GitHub Issues/PRs，不在 docs 中建立 RFC 或逐项工作档案。
- 中文和英文页面在 docs/zh 与 docs/en 镜像维护；站点导航配置见 mkdocs.yml，页面结构由 scripts/check_docs_structure.py 校验。

## 人格控制台预览与人格包

Mock 控制台使用 #/home、#/studio、#/memory、#/store、#/dream、
#/system?section=traces 等 hash 路由。预览选择器提供加载、空、错误和
1,000 节点／2,000 关联压力数据。预览中的安装、导入及编辑只操作内存数据。
dev:host 和生产构建必须使用已认证的 AstrBot 页面桥接器。

内置人格文件位于 persona_seeds/&lt;id&gt;/persona.json。新增时在 index.json
登记 ID，附带 LICENSE，并遵循[人格 seed 指南](persona-seed.md)。本地导入写入
插件数据目录的 persona_packs/。移除把文件移到 .trash，不改变当前人格。
恢复时检查备份 JSON 的 ID 和版本，再从“我的人格包”导入。覆盖同 ID 文件需要在
确认时提供当前版本；更新蓝图不会自动安装。
