# Testing and verification

## Test design

- Describe tests as behavior scenarios before writing assertions.
- Test only behavior callers can observe through a public boundary. Avoid assertions about private helpers, incidental call counts or internal layout.
- Add regression scenarios for changed behavior and failures affecting recovery, privacy or atomicity.
- Fake external systems at their boundary (`ChatModel`, AstrBot, clock, filesystem). Do not fake the unit under test or duplicate its implementation in a test.
- Keep pure core tests independent of SQLite unless persistence is the subject. Prefer existing DTOs such as `DialogueTurn`, `RetrievalCandidate` and `WriteOutcome`; do not add raw tuples where a named type belongs.

## Choose validation by risk

Run the narrowest checks that give adequate evidence. Use the [development guide](../../../../docs/zh/guides/development.md) for test layers and commands; do not run the full suite locally by habit.

| Change area | Local evidence to choose |
|---|---|
| Documentation or metadata only | Diff/links and format review |
| Isolated behavior in one module | Relevant unit layer plus focused regression scenario |
| Cross-layer behavior, privacy/disclosure, persistence or recovery | Relevant unit and integration/contract layers; inspect failure atomicity and privacy output |
| Recall or scoring | Relevant tests plus benchmark with before/after numbers |
| Public API or dashboard contract | Contract layer, backend contract export and frontend contract checks; add affected unit/integration layers, with type/lint checks when affected |
| AstrBot boundary | Real host or faithful staging verification when available; otherwise state the evidence gap |
| UI or visible copy | Review affected screens and copy using [UI quality guidance](ui-quality.md) |

CI runs the full required suite for every PR. Local risk-based validation does not reduce CI requirements. For an interface change, run the contract checks and every affected layer; the full suite is a local choice only when the change's blast radius warrants it. Record exact commands, outcomes and skipped checks with reasons in the GitHub PR description or completion report. Never claim checks that were not run.
