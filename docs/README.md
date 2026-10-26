# SeekMemory Documentation Map

This directory is the source of truth for design, contracts, invariants and test expectations.
The root README is the product entry point; this page is the contributor entry point.

## Status legend

| Status | Meaning |
|---|---|
| current | Matches the current `main` behavior and should be maintained |
| proposal | Not implemented yet; discussion or scope only |
| historical | Kept for audit and context; do not use as current contract |
| archive | Old baseline or investigation output; not a contract |

## Reading paths

### New contributor

1. [Repository development skill](../.agents/skills/seekmemory-dev/SKILL.md) for collaboration and implementation conventions
2. [ARCHITECTURE.md](ARCHITECTURE.md)
3. [INTERFACES.md](INTERFACES.md)
4. [INVARIANTS.md](INVARIANTS.md)
5. [TESTING.md](TESTING.md)
6. [DEV-SETUP.md](DEV-SETUP.md)
7. [CONTRACT.md](CONTRACT.md)

### Operator

1. [ARCHITECTURE.md](ARCHITECTURE.md)
2. [webui/README.md](webui/README.md)
3. [CONTRACT.md](CONTRACT.md)

### Reviewer

1. [INVARIANTS.md](INVARIANTS.md)
2. [TESTING.md](TESTING.md)
3. [CONTRACT.md](CONTRACT.md)

## Document index

| Document | Status | Purpose |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | current | Runtime path, layers and write/read boundaries |
| [CONTRACT.md](CONTRACT.md) | current | Public contracts and implementation notes |
| [INTERFACES.md](INTERFACES.md) | current | Protocols and DTOs for contributors |
| [INVARIANTS.md](INVARIANTS.md) | current | Non-negotiable identity, privacy, recovery and reinforcement rules |
| [TESTING.md](TESTING.md) | current | Test layers, commands and known coverage gaps |
| [DEV-SETUP.md](DEV-SETUP.md) | current | Local backend and dashboard setup |
| [DESIGN.md](DESIGN.md) | historical | Original design intent; implementation may differ |
| [INDEX.md](INDEX.md) | current | Code map and dependency direction |
| [BASELINES.md](BASELINES.md) | historical | Benchmark baseline notes |
| [BUGS.md](BUGS.md) | archive | Historical audit notes |
| [webui/README.md](webui/README.md) | current | WebUI operator guide |

## Documentation rules

- Current behavior belongs in ARCHITECTURE, CONTRACT, INTERFACES, INVARIANTS or TESTING.
- Proposed work belongs in a GitHub issue or an RFC, not in a current-contract document.
- Historical documents keep their original context and must say they are historical.
- Any data-structure change needs an entry in INVARIANTS and a contract test.
- Any public interface change needs an entry in INTERFACES and a contract test.

## Project tracking

Track planned work and review history in [GitHub Issues](https://github.com/NeverENG/SeekMemory/issues) and [Pull Requests](https://github.com/NeverENG/SeekMemory/pulls). Repository docs contain durable product and engineering guidance rather than copies of those work records.
