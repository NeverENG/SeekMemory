# core module

Primary interface / 主要接口：[interfaces.py](interfaces.py). It declares required
graph storage capabilities and exports provided domain operations without
implementing them / 集中声明外部依赖、导出领域能力，不包含业务实现。
Tree orchestration is provided by `services.TreeService`; its required ports live
in `app/ports.py` / 树操作由服务层负责，依赖接口在应用层声明；原 core 树入口已移除。

Module design and current contracts are maintained in the central bilingual documentation:

- [中文设计](../docs/zh/architecture/modules/core.md)
- [English design](../docs/en/architecture/modules/core.md)
- [Architecture overview](../docs/zh/architecture/overview.md)

The implementation under this directory is authoritative for concrete behavior.
