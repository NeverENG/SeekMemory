# Contract ownership and change workflow

Contracts have different owners. Use the current implementation as the source of truth and the architecture pages as a concise explanation; do not treat a copied signature or version-by-version Markdown snapshot as authoritative.

| Contract | Canonical owner | Keep aligned |
|---|---|---|
| Artifact shape and family semantics | `core/artifact.py`, `core/families/`, and the owning `core/` module | Family validation, relevant module design page, and behavior tests |
| Application ports and DTOs | `app/ports.py` and `app/contracts.py` | Calling services/adapters, the owning module page, and contract tests |
| SQLite schema and persisted data | `store/schema.sql`, `store/sqlite.py`, and repositories under `store/` | Compatible migrations, recovery behavior, and persistence tests; review [compatibility decisions](changelog-compatibility.md) before breaking changes |
| AstrBot plugin configuration | Root `_conf_schema.json` plus the defaults and reads in `adapters/` | Keep schema, runtime defaults, UI behavior, and user-facing guidance aligned; review compatibility before renaming or removing a setting |
| Management HTTP API | Root [`openapi.yaml`](../../../../openapi.yaml) | `webui/routes.py`, `services/management_service.py`, Zod runtime schemas, and API fixtures |
| Generated dashboard API types | `dashboard/src/contracts/generated.ts` | Regenerate from `openapi.yaml`; do not edit generated output by hand. See the [API change workflow](../../../../docs/en/guides/development.md#changing-the-management-api) and [dashboard README](../../../../dashboard/README.md). |

## Change sequence

1. Identify the caller-visible behavior and its owning implementation. Use the [architecture overview](../../../../docs/en/architecture/overview.md) and [module design pages](../../../../docs/en/index.md) to navigate; verify details in code.
2. Update the canonical owner first. For persistent formats or public configuration, settle compatibility and migration behavior before implementation.
3. Update every consumer and generated representation. For management API changes, regenerate dashboard types and keep backend validation and fixtures aligned.
4. Add or update caller-visible contract tests and any affected migration/recovery checks. Choose layers using the [testing reference](testing.md).
5. Update the relevant Chinese and English module pages when behavior or module boundaries change. Keep those pages descriptive; keep executable contracts in code, schemas, and tests.
