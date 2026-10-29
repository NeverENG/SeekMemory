"""Pure relationship fixtures shared without test-case imports.

共用纯关系样本，不导入测试类。
"""

from core.relationship_rules import (
    ConversationScope, RelationshipObservation, RelationshipReason,
    RelationshipScoringPolicy, RelationshipStrength, plan_relationship_revision,
)

def relationship_payload(**updates):
    payload = {
        "summary": "关系状态：中性",
        "affinity": 0.0,
        "confidence": 0.0,
        "evidence_count": 0,
        "relation_band": "neutral",
        "policy": {
            "version": "relationship-v1",
            "private_weight": 1.0,
            "group_weight": 0.5,
            "learning_rate": 0.25,
            "max_revision_delta": 0.1,
        },
    }
    payload.update(updates)
    return payload


def observation(
    artifact_id: str,
    reason: RelationshipReason,
    strength: RelationshipStrength,
    confidence: float,
    scope: ConversationScope,
) -> RelationshipObservation:
    return RelationshipObservation(
        artifact_id,
        "u1",
        reason,
        strength,
        confidence,
        (f"source-{artifact_id}",),
        scope,
    )
