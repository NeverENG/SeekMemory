# SeekMemory Docs

SeekMemory 为长期对话提供可追溯、可修订的记忆。文档只描述当前仓库的实现与操作方式，不复制 Issue、PR、RFC 或历史评测快照。

- [简体中文](zh/index.md)
- [English](en/index.md)

## 文档约定

- `docs/zh/` 与 `docs/en/` 保持镜像结构；
- 所有 Markdown 页面必须出现在 `mkdocs.yml` 的 `nav` 中；
- 宿主端口、运行协议等契约内容并入对应的模块页，不新增顶层孤立文档；
- Draft 页面的本地构建只检查结构；`main` 合并后发布 GitHub Pages。

本地检查：

```bash
python scripts/check_docs_structure.py
mkdocs build --strict
```
