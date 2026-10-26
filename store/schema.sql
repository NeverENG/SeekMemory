-- SeekMemory v3 存储结构。
-- 幂等：每次打开数据库时由 db.py 用 executescript 执行。
-- created_at/updated_at 之后追加的 revision、lineage 两列，是 CONTRACT 中
-- Header 要求的字段，v3 表清单未列出，缺了就无法无损往返。

CREATE TABLE IF NOT EXISTS blobs (
    hash    TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    op          TEXT NOT NULL,
    entity      TEXT NOT NULL,
    before_hash TEXT,
    after_hash  TEXT,
    reason      TEXT NOT NULL DEFAULT '',
    prev_hash   TEXT NOT NULL DEFAULT '',
    self_hash   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    family     TEXT NOT NULL,
    level      TEXT,
    parent     TEXT,
    blob       TEXT NOT NULL,
    state      TEXT NOT NULL DEFAULT 'active',
    scope      TEXT NOT NULL DEFAULT 'private',
    strength   TEXT NOT NULL DEFAULT '{}',
    time       TEXT NOT NULL DEFAULT '{}',
    said_by    TEXT NOT NULL DEFAULT 'owner',
    shareable  TEXT NOT NULL DEFAULT 'private_only',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    revision   INTEGER NOT NULL DEFAULT 1,
    lineage    TEXT NOT NULL DEFAULT '{}',
    subject_id TEXT NOT NULL DEFAULT ''
);

-- 版本链：每次落库都把自己的 revision 存一份，旧版本不丢。
-- 印象修订、记忆改正都能翻回"以前是怎么想的"。
CREATE TABLE IF NOT EXISTS versions (
    entity   TEXT NOT NULL,
    revision INTEGER NOT NULL,
    blob     TEXT NOT NULL,
    header   TEXT NOT NULL,
    at       TEXT NOT NULL,
    PRIMARY KEY (entity, revision)
);

CREATE TABLE IF NOT EXISTS edges (
    src    TEXT NOT NULL,
    dst    TEXT NOT NULL,
    kind   TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (src, dst, kind)
);

CREATE TABLE IF NOT EXISTS sources (
    id    TEXT PRIMARY KEY,
    umo   TEXT NOT NULL,
    at    TEXT NOT NULL,
    role  TEXT NOT NULL,
    blob  TEXT NOT NULL,
    flags TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS evidence (
    node   TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (node, source)
);

CREATE INDEX IF NOT EXISTS idx_nodes_family_state ON nodes(family, state);
CREATE INDEX IF NOT EXISTS idx_sources_at ON sources(at);
CREATE INDEX IF NOT EXISTS idx_nodes_level ON nodes(level);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_evidence_node ON evidence(node);

CREATE TABLE IF NOT EXISTS artifact_versions (
    seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity   TEXT NOT NULL,
    revision INTEGER NOT NULL,
    op       TEXT NOT NULL DEFAULT 'create',
    blob     TEXT NOT NULL,
    header   TEXT NOT NULL,
    at       TEXT NOT NULL,
    UNIQUE(entity, revision)
);

CREATE TABLE IF NOT EXISTS state_events (
    id            TEXT PRIMARY KEY,
    entity        TEXT NOT NULL,
    revision_seen INTEGER NOT NULL,
    op            TEXT NOT NULL,
    delta         TEXT NOT NULL DEFAULT '{}',
    at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_entity ON artifact_versions(entity, revision);
CREATE INDEX IF NOT EXISTS idx_state_entity ON state_events(entity, at);

CREATE TABLE IF NOT EXISTS artifact_evidence (
    entity   TEXT NOT NULL,
    revision INTEGER NOT NULL,
    source   TEXT NOT NULL,
    PRIMARY KEY (entity, revision, source)
);
CREATE INDEX IF NOT EXISTS idx_artifact_evidence_entity ON artifact_evidence(entity, revision);
CREATE INDEX IF NOT EXISTS idx_artifact_evidence_source ON artifact_evidence(source);

-- Pending extraction is a projection over immutable Source plus this state table.
-- Content is deliberately not duplicated here; queued rows are rebuilt by join.
-- state: pending | retrying | deferred | extracted | dead.
-- deferred rows wait for capacity headroom, dead rows exhausted max_attempts.
CREATE TABLE IF NOT EXISTS extraction_state (
    source_id       TEXT PRIMARY KEY,
    turn_id         TEXT NOT NULL DEFAULT '',
    session_id      TEXT NOT NULL,
    topic_id        TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL DEFAULT '',
    last_error      TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_extraction_state_queue
ON extraction_state(state, next_attempt_at, created_at, source_id);

-- Initialization imports keep task summaries after their Source links expire.
-- The source association is removed when a task reaches a terminal state.
CREATE TABLE IF NOT EXISTS history_import_tasks (
    id               TEXT PRIMARY KEY,
    status           TEXT NOT NULL DEFAULT 'queued',
    stage_key        TEXT NOT NULL DEFAULT '',
    selection_json   TEXT NOT NULL DEFAULT '{}',
    format_id        TEXT NOT NULL DEFAULT 'chatlab',
    source_count     INTEGER NOT NULL DEFAULT 0,
    duplicate_count  INTEGER NOT NULL DEFAULT 0,
    skipped_count    INTEGER NOT NULL DEFAULT 0,
    pending_count    INTEGER NOT NULL DEFAULT 0,
    extracted_count  INTEGER NOT NULL DEFAULT 0,
    failed_count     INTEGER NOT NULL DEFAULT 0,
    error_types      TEXT NOT NULL DEFAULT '[]',
    persona_status   TEXT NOT NULL DEFAULT 'pending',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    terminal_at      TEXT NOT NULL DEFAULT '',
    stage_expires_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS history_import_sources (
    task_id   TEXT NOT NULL,
    source_id TEXT NOT NULL,
    topic_id  TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY (task_id, source_id)
);

CREATE TABLE IF NOT EXISTS history_import_preflight (
    stage_key  TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    topic_id   TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT '',
    reply_to   TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (stage_key, source_id)
);

CREATE INDEX IF NOT EXISTS idx_history_import_sources_topic
ON history_import_sources(task_id, topic_id, source_id);
CREATE INDEX IF NOT EXISTS idx_history_import_tasks_retention
ON history_import_tasks(status, terminal_at);

-- 梦境周期台账：每天一次，记录这次"睡觉"抽了什么、改了什么。
-- 主键是日期，天然幂等：同一天重复触发只会被这个表挡住。
CREATE TABLE IF NOT EXISTS dream_runs (
    dream_date  TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'planned',
    started_at  TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    batches     INTEGER NOT NULL DEFAULT 0,
    written     INTEGER NOT NULL DEFAULT 0,
    errors      TEXT NOT NULL DEFAULT '[]',
    summary     TEXT NOT NULL DEFAULT '{}'
);

-- Runtime state is mutable scheduler state, separate from Source/Artifact memory.
CREATE TABLE IF NOT EXISTS runtime_state (
    session_id TEXT PRIMARY KEY,
    payload    TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT ''
);

-- Runtime episodes are append-only metadata/audit records, not memory artifacts.
CREATE TABLE IF NOT EXISTS runtime_episodes (
    id                  TEXT PRIMARY KEY,
    at                  TEXT NOT NULL,
    session_id          TEXT NOT NULL,
    decision            TEXT NOT NULL DEFAULT '',
    reason              TEXT NOT NULL DEFAULT '',
    action              TEXT NOT NULL DEFAULT '',
    delivered           INTEGER NOT NULL DEFAULT 0,
    response_chars      INTEGER NOT NULL DEFAULT 0,
    tool_calls          TEXT NOT NULL DEFAULT '[]',
    outcome             TEXT NOT NULL DEFAULT '',
    error               TEXT NOT NULL DEFAULT '',
    user_source_id      TEXT NOT NULL DEFAULT '',
    assistant_source_id TEXT NOT NULL DEFAULT '',
    run_id              TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runtime_episodes_session
ON runtime_episodes(session_id, at, id);
