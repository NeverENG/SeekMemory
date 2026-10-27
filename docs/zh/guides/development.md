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

    mkdocs build --strict

## 后端验证层

脚本依据 tests/layers.py 把平铺的 unittest 文件分为多个责任层。按改动选择适当范围：

    python3 scripts/run_tests.py --layer unit
    python3 scripts/run_tests.py --layer contract
    python3 scripts/run_tests.py --layer integration
    python3 scripts/run_tests.py --layer host
    python3 scripts/run_tests.py --layer smoke
    python3 scripts/run_tests.py --layer all

也可直接运行全部兼容测试文件：

    python3 -m unittest discover -s tests -p 'test_*.py' -q

测试不会自动证明真实模型的抽取质量，也不会在没有 AstrBot 的环境里证明宿主行为。模型评估和容量探测属于单独的人工流程；参见 [benchmarks/README.md](../../../benchmarks/README.md)。

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
