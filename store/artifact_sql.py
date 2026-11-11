"""Artifact statement templates; no serialization, execution or resources.

记忆 SQL 语句模板，不进行序列化、执行或资源管理。
"""

SELECT_SQL = (
    "SELECT n.*, b.content AS blob_content FROM nodes n "
    "LEFT JOIN blobs b ON b.hash = n.blob"
)
# Never evaluate JSON functions on malformed legacy text. Only finite,
# nonnegative JSON numbers are weights; all other values use Strength's 1.0.
GRAPH_WEIGHT_SQL = (
    "CASE WHEN json_valid(strength) THEN CASE "
    "WHEN json_type(strength, '$.weight') IN ('integer', 'real') "
    "AND json_extract(strength, '$.weight') BETWEEN 0 AND 1.7976931348623157e308 "
    "THEN json_extract(strength, '$.weight') ELSE 1.0 END ELSE 1.0 END"
)

UPSERT_SQL = (
    "INSERT INTO nodes(id, family, level, parent, blob, state, scope, strength, time, "
    "said_by, shareable, created_at, updated_at, revision, lineage, subject_id) "
    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
    "family=excluded.family, level=excluded.level, "
    "blob=excluded.blob, "
    "state=excluded.state, scope=excluded.scope, strength=excluded.strength, "
    "time=excluded.time, said_by=excluded.said_by, shareable=excluded.shareable, "
    "revision=excluded.revision, lineage=excluded.lineage, subject_id=excluded.subject_id, "
    "updated_at=excluded.updated_at, "
    "created_at=CASE WHEN nodes.created_at = '' THEN excluded.created_at "
    "ELSE nodes.created_at END"
)
