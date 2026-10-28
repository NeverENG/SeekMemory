# core module

Primary interface / 主要接口：[interfaces.py](interfaces.py). It declares required
storage/cache capabilities and exports provided domain operations without
implementing them / 集中声明外部依赖、导出领域能力，不包含业务实现。
Existing import paths remain compatible / 原导入路径继续兼容。

Module design and current contracts are maintained in the central bilingual documentation:

- [中文设计](../docs/zh/architecture/modules/core.md)
- [English design](../docs/en/architecture/modules/core.md)
- [Architecture overview](../docs/zh/architecture/overview.md)

The implementation under this directory is authoritative for concrete behavior.
