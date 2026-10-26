# 贡献指南

仓库级开发约定统一维护在 [SeekMemory development skill](.agents/skills/seekmemory-dev/SKILL.md) 及其 reference，适用于代码、测试、文档、配置、UI、分支和 worktree。技术事实以对应的 `docs/` 契约为准；目录入口见 [docs/INDEX.md](docs/INDEX.md)，测试层级见 [docs/TESTING.md](docs/TESTING.md)。

所有改动都在非 `main` 分支完成。CI 对每个 PR 执行完整必需检查；开发者本地按改动风险选择足够的验证，并记录命令和结果。P0/P1 工作通过 GitHub Issue 和 PR 跟踪；长期有效的技术事实和决策写入对应的 `docs/` 文档，不复制 issue/PR 工作记录。生产改动和发布由 Lead 负责。

<a id="release-packaging"></a>

## 发布打包

`.github/workflows/release.yml` 在 PR 和手动触发时构建、测试可安装的分发包，上传包含插件 ZIP 和校验文件的 Actions 构件，保留七天；这两种触发方式不创建 Release。

正式发布只能由 Lead 执行。评审合并后的发布步骤：

1. 在短期分支 `release/X.Y.Z` 更新 `metadata.yaml` 和 `CHANGELOG.md`，评审并合并后再打标签。
2. 在已评审的提交上推送 `vX.Y.Z` 标签。标签必须与 metadata 版本完全一致，支持 `1.2.3-rc.1` 等预发布版本。
3. CI 按锁文件安装前端依赖，执行严格前端检查和 Python 测试，构建生产资源，按运行文件白名单打包。
4. 独立任务使用已有标签发布 `astrbot_plugin_seekmemory.zip` 和 `SHA256SUMS`。预发布标签对应预发布版本；已有 Release 不会被覆盖，重复发布会失败，需检查原因。

安装包包含 Git 跟踪的 `app`、`core`、`store`、`recall`、`perceive`、`maintain`、`webui` 下的 `.py`，以及 `main.py`、元数据、配置定义、`store/schema.sql`、许可证和 `pages/memory` 生产资源。新增运行资源或包时，同步修改 `scripts/package_plugin.py` 和打包验证。构建产物不提交到 Git，源码归档保持源码形态。后端无需编译，分发 `.py` 以保持 Python 和平台兼容性。

本地打包使用根目录 README 中的构建命令。先运行 `python -m pip install -r requirements-dev.txt` 安装仅供开发使用的契约测试依赖。发布前运行 `python -m unittest discover -s tests -p 'test_*.py'` 和 `python tests/test_smoke.py`。打包验证会解压 ZIP，在独立 Python 进程中执行后端冒烟测试。

安装了兼容宿主时，`tests/test_webui_host.py` 还会验证真实 AstrBot 请求上下文和插件生命周期。独立 CI 跳过这些宿主专用测试；存储、scope、修订和任务测试无需 AstrBot。测试不会启动消息适配器或调用付费模型。修改 API 时先更新 `openapi.yaml`，运行 `cd dashboard && pnpm generate:api`，再同步 Zod 校验、桥接适配器和实现验证。`pnpm check` 检查生成类型是否过期，随后执行 TypeScript、lint、Mock 契约和格式检查。

真实响应的跨语言验证在插件根目录执行：

```bash
python tests/test_api_contract.py --export dashboard/node_modules/.tmp/backend-contract.json
pnpm --dir dashboard test:contract
```

该步骤执行真实路由、数据库、修订、诊断与任务代码，仅替代宿主传输对象；缺少导出的响应会使前端检查失败。已安装 AstrBot 时，宿主集成验证还会对实际 `JSONResponse` 执行同一契约校验。CI 与发布构建均执行这些检查；契约、生成工具、测试依赖与临时响应不进入安装包。

安装使用 Release 附件。若希望通过自定义插件源自动安装或更新，应将该源的 `download_url` 指向 Release 附件地址；仅填写仓库地址不会自动选择发布附件。

本节锚点由 `docs/CONTRACT.md` 和 `dashboard/README.md` 引用。协作、验证和编码约定见 [development skill](.agents/skills/seekmemory-dev/SKILL.md)。
