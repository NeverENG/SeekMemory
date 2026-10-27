# SeekMemory 管理界面

## 本地开发

使用 Node.js 26 和 pnpm 10，在本目录执行：

```bash
pnpm install --frozen-lockfile
pnpm dev
```

默认地址为 `http://127.0.0.1:5176`。Mock 模式无需启动 AstrBot，顶部可切换预览场景和主题。
数据仅保存在内存，刷新后重置；不会修改真实记忆，模拟诊断也不代表真实召回效果。

`pnpm dev:host` 需要 AstrBot 注入宿主桥接器，直接打开会显示连接错误。
正式使用从 AstrBot 插件卡片打开视图，见[使用说明](../docs/zh/guides/webui.md)。

## 检查与构建

```bash
pnpm check
pnpm build
```

`check` 包含生成类型检查、TypeScript、lint、测试和格式检查；格式修复使用 `pnpm format`。
构建输出到 `../pages/memory/`，产物不提交 Git。安装包由 Release 流程生成，
源码下载不包含预构建页面，见[发布说明](../CONTRIBUTING.md#release-packaging)。

## 接口契约与类型生成

修改管理 API 时同步根目录 `openapi.yaml`，然后在本目录执行：

```bash
pnpm generate:api
pnpm check
```

生成的 `src/contracts/generated.ts` 需要提交，不手工编辑。
验证真实后端响应与前端契约时，在**插件根目录**执行：

```bash
python -m pip install -r requirements-dev.txt
python tests/test_api_contract.py --export dashboard/node_modules/.tmp/backend-contract.json
pnpm --dir dashboard test:contract
```
