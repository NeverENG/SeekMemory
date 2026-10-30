"""Validate explicit management commands, commit revisions, then publish cache.

校验明确的管理命令，提交版本后更新缓存；不负责查询或管理资源生命周期。
"""
from __future__ import annotations

import dataclasses
import json

try:
    from ..app.ports import ArtifactStore, ArtifactCache, PersonaPacks
    from ..core.domain.memory.artifact import Lineage, Strength, make, revise, validate
    from ..core.domain.character.bot_behavior import SELF_SUBJECT
    from ..core.domain.character.persona import PERSONA_ORIGIN_SEED, persona_payload_from_file
    from ..core.domain.memory.versioning import VersionError
except ImportError:
    from app.ports import ArtifactStore, ArtifactCache, PersonaPacks
    from core.domain.memory.artifact import Lineage, Strength, make, revise, validate
    from core.domain.character.bot_behavior import SELF_SUBJECT
    from core.domain.character.persona import PERSONA_ORIGIN_SEED, persona_payload_from_file
    from core.domain.memory.versioning import VersionError

from .management_queries import pack_digest, json_object, _persona_version_header

def update(artifacts: ArtifactStore, cache: ArtifactCache, body: dict) -> str:
    """Validate a confirmed memory edit, commit with CAS and then update cache / 验证已确认的记忆修改，按预期版本提交后再更新缓存。"""
    if set(body) != {
        "id",
        "expectedRevision",
        "payload",
        "scope",
        "state",
        "reason",
        "confirmed",
    }:
        raise ValueError("编辑字段缺失或包含未支持的字段")
    if body["confirmed"] is not True:
        raise ValueError("请先确认操作")
    if type(body["expectedRevision"]) is not int or not isinstance(body["id"], str):
        raise ValueError("版本号或 ID 无效")
    valid_scope = body["scope"] in ("private", "shared", "shadow")
    valid_state = body["state"] in ("active", "forgotten", "merged")
    if not valid_scope or not valid_state:
        raise ValueError("状态或 scope 无效")
    if (
        not isinstance(body["reason"], str)
        or not 1 <= len(body["reason"].strip()) <= 300
    ):
        raise ValueError("请填写 1–300 个字符的修改原因")
    if (
        not isinstance(body["payload"], dict)
        or len(json.dumps(body["payload"])) > 50000
    ):
        raise ValueError("记忆内容必须为 JSON 对象，序列化后不超过 50,000 个字符")
    art = artifacts.get(body["id"])
    if art is None:
        raise LookupError("记忆不存在")
    if art.header.state == "merged" and body["state"] != "merged":
        raise ValueError("已合并的记忆不能独立恢复")
    if art.header.state != "merged" and body["state"] == "merged":
        raise ValueError("请通过维护任务合并记忆，以保留派生关系")
    replacement = revise(
        art, payload=body["payload"], scope=body["scope"], state=body["state"]
    )
    validate(replacement)
    try:
        artifacts.commit(
            replacement,
            expected_revision=body["expectedRevision"],
            op="forget" if body["state"] == "forgotten" else "revise",
            reason=body["reason"].strip(),
            source_ids=tuple(replacement.header.lineage.sources),
        )
    except VersionError as exc:
        raise ValueError("revision_conflict") from exc
    cache.put(replacement)
    return replacement.header.id


def bootstrap_persona(artifacts: ArtifactStore, cache: ArtifactCache, seed_file: dict) -> dict:
    """Commit an authored seed and retire other personas atomically; create no Source / 原子提交人工设定并停用其他人格，不创建原始消息。"""
    payload = persona_payload_from_file(seed_file)
    active = sorted(cache.active("persona"), key=lambda art: (
        art.header.subject_id != SELF_SUBJECT,
        art.header.time.created,
        art.header.id,
    ))
    base = active[0] if active else None
    strength = Strength(confidence=1.0)
    common = dict(
        subject_id=SELF_SUBJECT,
        scope="shared",
        shareable="public",
        said_by=PERSONA_ORIGIN_SEED,
        state="active",
        strength=strength,
        lineage=Lineage(),
    )
    if base is None:
        persona = make("persona", payload, **common)
        expected = 0
    else:
        persona = revise(base, payload=payload, **common)
        expected = base.header.revision
    writes = [(persona, expected, ())]
    retired = [revise(art, state="merged") for art in active[1:]]
    writes.extend((art, art.header.revision - 1, ()) for art in retired)
    artifacts.commit_many(
        writes, op="promote", reason="persona seed bootstrap"
    )
    cache.put(persona)
    for art in retired:
        cache.remove(art.header.id)
    return {
        "id": persona.header.id,
        "revision": persona.header.revision,
        "seedId": str(payload["seed_id"]),
        "seedVersion": str(payload["seed_version"]),
    }


def rollback_persona(artifacts: ArtifactStore, cache: ArtifactCache, body: dict) -> dict:
    """Restore a historical persona as a new revision without deleting history / 将历史人格恢复为新版本，不删除历史。"""
    if set(body) != {"id", "revision", "reason", "confirmed"}:
        raise ValueError("回滚字段缺失或包含未支持的字段")
    if body["confirmed"] is not True:
        raise ValueError("请先确认操作")
    if not isinstance(body["id"], str) or type(body["revision"]) is not int:
        raise ValueError("ID 或 revision 无效")
    if body["revision"] < 1:
        raise ValueError("revision 必须大于 0")
    reason = body["reason"]
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 300:
        raise ValueError("请填写 1–300 个字符的回滚原因")
    current = artifacts.get(body["id"])
    if current is None:
        raise LookupError("记忆不存在")
    if current.header.family != "persona":
        raise ValueError("只能回滚 persona")
    if current.header.state != "active":
        raise ValueError("只能回滚 active persona")
    target = next(
        (row for row in artifacts.history(current.header.id)
         if int(row.get("revision") or 0) == body["revision"]),
        None,
    )
    if target is None or not isinstance(target.get("payload"), dict):
        raise ValueError("目标 persona revision 不存在")
    if target["revision"] == current.header.revision:
        raise ValueError("目标 revision 已经是当前版本")
    snapshot = _persona_version_header(artifacts, current.header.id, target["revision"])
    raw_lineage = json_object(snapshot.get("lineage"))
    lineage = Lineage(
        sources=tuple(str(value) for value in raw_lineage.get("sources", ()) if value),
        derived_from=tuple(
            str(value) for value in raw_lineage.get("derived_from", ()) if value
        ),
    )
    raw_strength = json_object(snapshot.get("strength"))
    strength = Strength(
        **{
            field.name: raw_strength[field.name]
            for field in dataclasses.fields(Strength)
            if field.name in raw_strength
        }
    )
    payload = dict(target["payload"])
    said_by = "seed" if payload.get("origin") == PERSONA_ORIGIN_SEED else "inferred"
    replacement = revise(
        current,
        payload=payload,
        state="active",
        scope=str(snapshot.get("scope") or "shared"),
        subject_id=str(snapshot.get("subject_id") or SELF_SUBJECT),
        said_by=said_by,
        shareable="public",
        lineage=lineage,
        strength=strength,
    )
    validate(replacement)
    artifacts.commit(
        replacement,
        expected_revision=current.header.revision,
        op="revise",
        reason=reason.strip(),
        source_ids=tuple(lineage.sources),
    )
    cache.put(replacement)
    return {
        "id": replacement.header.id,
        "revision": replacement.header.revision,
        "restoredRevision": target["revision"],
    }


def persona_action(artifacts: ArtifactStore, cache: ArtifactCache, packs: PersonaPacks | None, body: dict) -> dict:
    """Validate one confirmed pack action; installing uses revision and digest checks / 验证一次已确认的人格包操作，安装时检查版本与内容摘要。"""
    if packs is None:
        raise RuntimeError("人格包目录不可用")
    if body.get("confirmed") is not True:
        raise ValueError("请先确认操作")
    operation = body.get("operation")
    fields = {
        "import": {"operation", "seed", "confirmed"},
        "importPack": {"operation", "pack", "confirmed"},
        "remove": {"operation", "reference", "confirmed"},
        "install": {"operation", "reference", "expectedId", "expectedRevision", "expectedDigest", "confirmed"},
    }
    if not isinstance(operation, str) or operation not in fields or set(body) - ({"expectedVersion"} if operation in {"import", "importPack"} else set()) != fields[operation]:
        raise ValueError("人格操作字段无效")

    reference = body.get("reference", "")
    if not isinstance(reference, str):
        raise ValueError("人格包标识无效")
    if operation in {"import", "importPack"}:
        expected = body.get("expectedVersion")
        if "expectedVersion" in body and not isinstance(expected, str):
            raise ValueError("人格包版本无效")
        return {"reference": packs.save(body.get("seed" if operation == "import" else "pack"), expected)}
    if operation == "remove":
        packs.remove(reference)
        return {"reference": reference}
    if operation != "install":
        raise ValueError("未知人格操作")
    current = sorted(cache.active("persona"), key=lambda art: (
        art.header.subject_id != SELF_SUBJECT, art.header.time.created, art.header.id))
    base = current[0] if current else None
    if (body.get("expectedId") != (base.header.id if base else None)
            or type(body.get("expectedRevision")) is not int
            or body["expectedRevision"] != (base.header.revision if base else 0)):
        raise ValueError("revision_conflict")
    bundle = packs.bundle(reference)
    if body.get("expectedDigest") != pack_digest(bundle):
        raise ValueError("pack_changed")
    return bootstrap_persona(artifacts, cache, bundle["seed"])
