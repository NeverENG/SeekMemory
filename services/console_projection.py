"""Read bounded console projections; no Source bodies or writes.

读取有数量上限的控制台视图，不读取原始消息正文或执行写入。
"""
from __future__ import annotations

try:
    from ..core.domain.memory.artifact import Artifact, content_of
    from ..app.ports import ArtifactStore
except ImportError:
    from core.domain.memory.artifact import Artifact, content_of
    from app.ports import ArtifactStore


def protected(art: Artifact) -> bool:
    """Decide whether a management card must hide its text / 判断管理卡片是否需要隐藏正文。"""
    return art.header.scope == "shadow" or art.header.family in {"secret", "designated"}


def kind(art: Artifact) -> str:
    """Read the displayed family or memory level / 读取展示用类型或记忆层级。"""
    if art.header.family == "memory":
        return str(art.payload.get("level", "detail"))
    return art.header.family


def graph(artifacts: ArtifactStore, *, limit: int = 120) -> dict:
    """Read a bounded graph projection without Source bodies / 读取有数量上限且不含原始消息正文的图视图。"""
    rows = artifacts.list_recent(limit)
    edge_limit = limit * 2
    nodes = [{
        "id": a.header.id, "kind": kind(a), "scope": a.header.scope,
        "subject": a.header.subject_id, "state": a.header.state,
        "label": "受保护的记忆" if protected(a) else (content_of(a)[:60] or "未命名记忆"),
        "createdAt": a.header.time.created, "updatedAt": a.header.time.updated,
        "confidence": max(0, min(1, a.header.strength.confidence)),
        "protected": protected(a),
    } for a in rows]
    visible = {a.header.id for a in rows}
    edges = {}

    def add(source: str, target: str, relation: str) -> None:
        """Add a bounded unique node to the projection.

        向投影加入有数量上限的唯一节点。
        """
        if source != target and source in visible and target in visible and len(edges) < edge_limit:
            key = (min(source, target), max(source, target), relation)
            edges[key] = {"source": source, "target": target, "kind": relation}

    for edge in artifacts.edges_between([a.header.id for a in rows], edge_limit):
        add(edge.source, edge.target, "related")
    subjects, evidence = {}, {}
    for art in rows:
        aid = art.header.id
        for target in art.header.lineage.derived_from:
            add(aid, target, "derived_from")
        subject = art.header.subject_id
        if subject:
            if subject in subjects:
                add(aid, subjects[subject], "same_subject")
            subjects[subject] = aid
        for source in art.header.lineage.sources:
            if source in evidence:
                add(aid, evidence[source], "evidence")
            evidence[source] = aid
    return {"nodes": nodes, "edges": list(edges.values()), "total": artifacts.count(), "limit": limit}


def impressions(artifacts: ArtifactStore, *, offset: int, limit: int) -> dict:
    """Read one bounded management impression page / 读取一页有数量上限的管理印象。"""
    rows = artifacts.list_impressions(limit=limit, offset=offset)
    cards = []
    for art in rows:
        subject = art.header.subject_id
        subject_kind = str(art.payload.get("subject_kind", "unknown"))
        if subject == "bot:self":
            subject_kind = "self"
        cards.append({
            "id": art.header.id, "subjectId": subject, "subjectKind": subject_kind,
            "displayName": "自己" if subject == "bot:self" else subject,
            "summary": "受保护的印象，点击查看" if protected(art) else content_of(art)[:160],
            "scope": art.header.scope, "confidence": max(0, min(1, art.header.strength.confidence)),
            "evidenceCount": len(set(art.header.lineage.sources)),
            "revision": art.header.revision, "updatedAt": art.header.time.updated,
        })
    return {"items": cards, "total": artifacts.count_impressions(),
            "offset": offset, "limit": limit}


def dreams(rows: list[dict]) -> dict:
    """Project recent run counts without prompts or responses / 转换近期运行计数，不包含提示词或回复。"""
    def count(value: object) -> int:
        """Normalize a nonnegative numeric run count.

        整理非负数值运行计数。
        """
        return max(0, int(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
    entries = []
    for row in rows[:100]:
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        usage = summary.get("usage") if isinstance(summary.get("usage"), dict) else {}
        status = str(row.get("status", "unknown"))
        budget = summary.get("budget") if isinstance(summary.get("budget"), dict) else {}
        triage = summary.get("triage") if isinstance(summary.get("triage"), dict) else {}
        entries.append({
            **{key: count(triage[key]) if type(triage.get(key)) is int else None
               for key in ("candidates", "eligible", "selected", "skipped", "pending")},
            "stopped": budget.get("stopped") if budget.get("stopped") in {"call_budget", "token_budget"} else "",
            "date": str(row.get("date", "")),
            "status": status if status in {"running", "done", "failed"} else "unknown",
            "batches": count(row.get("batches")), "written": count(row.get("written")),
            "calls": count(usage.get("calls")), "usageIn": count(usage.get("in")),
            "usageOut": count(usage.get("out")),
            "errorCount": len(row.get("errors", [])) if isinstance(row.get("errors"), list) else 0,
        })
    return {"items": entries, "limit": 100}
