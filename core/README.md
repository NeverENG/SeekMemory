# core module

Provided interface / 对外能力入口：[domain.py](domain.py). It explicitly exports
domain values and operations without implementing them / 集中导出领域类型和操作，不包含业务实现。
Required ports / 外部依赖声明：[ports.py](ports.py). It declares the graph storage
capabilities callers supply / 声明外部需要提供的图存储能力，不包含具体实现。
Tree orchestration is provided by `services.TreeService`; its required ports live
in `app/ports.py` / 树操作由服务层负责，依赖接口在应用层声明；原 core 树入口已移除。

Module design and current contracts are maintained in the central bilingual documentation:

- [中文设计](../docs/zh/architecture/modules/core.md)
- [English design](../docs/en/architecture/modules/core.md)
- [Architecture overview](../docs/zh/architecture/overview.md)

The implementation under this directory is authoritative for concrete behavior.
