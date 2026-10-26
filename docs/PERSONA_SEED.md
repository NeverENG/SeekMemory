# Persona File and Bootstrap

## Purpose

A persona file is authored configuration that initializes the one active persona
chain. It is not a Source, not chat evidence, and not a second runtime profile.

The seed-content owner authors files. `ManagementService.bootstrap_persona()` is
the admin write path. After bootstrap, Dream owns further persona revisions.

## File format

A persona file is a UTF-8 JSON object. The snippet below is abridged; see
`docs/examples/persona.*.json` for valid files with a full corpus.

```json
{
  "id": "big_fish",
  "version": "1.0.0",
  "name": "大肥鱼",
  "persona": "你是大肥鱼，说话温柔但有点嘴硬。",
  "style": {
    "tone": "温柔嘴硬",
    "sentence_length": "short"
  },
  "boundaries": [
    "不伪造用户经历",
    "不透露私人 Source 原文"
  ],
  "corpus": [
    {"user": "今天好累。", "assistant": "先歇一下嘛，我陪你。"}
  ],
  "license": "CC0-1.0",
  "source": "original",
  "content_rating": "general",
  "locale": "zh-CN"
}
```

### Required fields

| Field | Rule |
|---|---|
| `id` | Lowercase letters, digits, `.`, `_`, `-`; 2–64 chars |
| `version` | Non-empty string, max 32 chars |
| `name` | Non-empty display name, max 80 chars |
| `persona` | Non-empty persona text, max 20,000 chars |
| `corpus` | Optional authored dialogue corpus; if present, at least 12 pairs and 1,200 chars |

`persona_text` is accepted as a compatibility alias for `persona` in the early
draft, but new files should use `persona`.

### Optional fields

- `style`: bounded JSON object; used by future composition, not evidence.
- `boundaries`: bounded string array.
- `corpus`: authored style dialogues. It is optional so a direct persona can be
  configured, but a convincing seed pack should provide a substantial corpus
  (minimum 12 pairs / 1,200 chars when present). Corpus is stored only on the
  one-time bootstrap revision; Dream revisions keep only `corpus_count` and
  `corpus_hash` as provenance. It is **not** chat evidence and is **not**
  injected into recall.
- `license`, `source`, `content_rating`, `locale`.

Unknown fields are rejected so the file format cannot silently absorb unsafe
metadata.

## Bootstrap contract

`bootstrap_persona(persona_file)`:

1. validates the file;
2. finds the current active persona;
3. creates or revises the same persona Artifact id;
4. writes payload provenance (`origin=seed`, `seed_id`, `seed_version`,
   `seed_license`, `seed_source`, style, boundaries, corpus_count,
   corpus_hash); when a corpus is supplied, the one-time bootstrap revision
   also stores the full corpus for authoring/audit;
5. sets the persona header to `bot:self`, `shared`, `public`, `said_by=seed`;
6. commits atomically and updates cache;
7. retires duplicate active persona rows if legacy data contains them;
8. returns id, revision and seed provenance.

It must not:

- create a Source;
- call extraction or Dream;
- write a second PersonaProfile table;
- let the WebUI write storage directly.

## After bootstrap

The initial seed persona is trusted for recall. Dream may later synthesize the
same persona Artifact lineage from:

```text
current active persona text
  + self-impressions
  + bounded shared memory summaries
  = new persona Artifact revision on the same id
```

This is an incremental revision: the current persona is the authoritative base,
not a from-scratch rewrite. The synthesis step uses at most one bounded model
call per eligible Dream cycle. It does not include raw Source text or the full
corpus. The one-time bootstrap revision stores the authored corpus (if supplied);
subsequent revisions keep only `corpus_count` and `corpus_hash`.

The default synthesis interval is seven days (`persona_synthesis_interval_days`).
The previous revision remains in history. Manual edits and rollback use the same
persona Artifact lineage. `POST manage/rollbackPersona` restores a historical
revision by creating a new revision with the target payload and header snapshot;
it never deletes history and never creates a parallel persona store.

## CLI bootstrap

```bash
python scripts/bootstrap_persona.py --db <memory.db> --file <persona.json>
python scripts/bootstrap_persona.py --db <memory.db> --file <persona.json> --dry-run
```

脚本只调用 `ManagementService.bootstrap_persona()`：不创建 Source、不触发抽取、
不写第二份人格存储。`--dry-run` 只校验文件并打印 seed id/version、语料数量和文本长度。

写入后人格由召回常驻层每轮注入；`budget_chars` 需要足够大（人格文本 + 常驻印象），
否则人格会被预算裁剪影响可用长度。

## Trust rules

- Seed-origin persona: trusted only with explicit seed provenance and an active
  `bot:self` shared/public header; when a corpus is present, its count/hash must
  match.
- Dream-origin persona: must retain evidence lineage and the existing
  confidence/derived-from checks.
- Legacy behavior-derived persona: preserve the existing fixed-text rules.
- Arbitrary unverified persona text: never injected.

## Storage

- Authored files: `persona_seeds/` (read-only runtime data, packaged by the
  seed/store owner).
- Installed state: persona Artifact rows plus payload provenance.
- No separate active persona profile table is needed for this bootstrap.
- Chat imports remain Source/Dream writes; they are not persona files.
