"""Offline semantic verifier evaluation against an OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import ChatRequest, ChatResponse
from core.relationship_rules import (
    ConversationScope, RelationshipCandidate, RelationshipReason,
    RelationshipStrength, VerifiedRelationshipEvent,
)
from core.source import Source
from perceive.relationship import verify_relationship


def load_cases(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


class EndpointChatModel:
    """Translate the shared ChatModel contract into an offline endpoint call."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return await asyncio.to_thread(self._complete, request)

    def _complete(self, request: ChatRequest) -> ChatResponse:
        body = json.dumps({
            "model": request.model or self.model, "temperature": request.temperature,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.prompt},
            ],
        }).encode("utf-8")
        http_request = urllib.request.Request(
            self.url, data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key},
        )
        with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
            data = json.load(response)
        return ChatResponse(text=data["choices"][0]["message"]["content"], model=self.model)


async def evaluate(cases: list[dict], model: EndpointChatModel) -> dict:
    results = []
    for case in cases:
        sources = tuple(Source(**item) for item in case["sources"])
        spec = case["candidate"]
        candidate = RelationshipCandidate(
            subject_id=spec["subject_id"], reason=RelationshipReason(spec["reason"]),
            strength=RelationshipStrength(spec.get("strength", "strong")),
            primary_source_id=spec["primary_source_id"], source_ids=tuple(spec["source_ids"]),
            session_id=spec["session_id"], scope=ConversationScope(spec.get("scope", "private")),
        )
        priors = tuple(VerifiedRelationshipEvent(
            event_id=row["event_id"], subject_id=row["subject_id"],
            reason=RelationshipReason(row["reason"]),
            strength=RelationshipStrength(row.get("strength", "strong")),
            scope=ConversationScope(row.get("scope", "private")),
            event_at=datetime.fromisoformat(row["event_at"]),
            primary_source_id=row["primary_source_id"], source_ids=tuple(row["source_ids"]),
        ) for row in case.get("prior_negative", ()))
        verdict = await verify_relationship(candidate, sources, model, priors)
        results.append({
            "id": case["id"], "expected": case["expected"],
            "verdict": verdict.status, "repair_of": verdict.repair_of,
            "correct": verdict.status == case["expected"],
        })
    negatives = [row for row in results if row["expected"] == "abstain"]
    positives = [row for row in results if row["expected"] == "verified"]
    return {
        "status": "measured", "model": model.model, "cases": len(results),
        "verified": sum(row["verdict"] == "verified" for row in results),
        "coverage": sum(row["verdict"] == "verified" for row in results) / len(results) if results else None,
        "positive_coverage": sum(row["verdict"] == "verified" for row in positives) / len(positives) if positives else None,
        "negative_false_positives": sum(row["verdict"] == "verified" for row in negatives),
        "negative_cases": len(negatives),
        "negative_false_positive_rate": sum(row["verdict"] == "verified" for row in negatives) / len(negatives) if negatives else None,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(Path(__file__).with_name("relationship_cases.jsonl")))
    parser.add_argument("--base-url", default=os.environ.get("SEEKMEMORY_EVAL_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("SEEKMEMORY_EVAL_API_KEY", ""))
    parser.add_argument("--model", default=os.environ.get("SEEKMEMORY_EVAL_MODEL", ""))
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    cases = load_cases(args.cases)
    if not (args.base_url and args.api_key and args.model):
        report = {"status": "unavailable", "cases": len(cases), "reason": "model endpoint, API key and model are required"}
    else:
        report = asyncio.run(evaluate(cases, EndpointChatModel(args.base_url, args.api_key, args.model, args.timeout)))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
