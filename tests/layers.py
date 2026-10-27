"""Test-layer map for local runs and CI.

The test files stay flat for unittest compatibility. This map gives each file one
primary responsibility so reviewers can run only the layer they changed.
"""

from __future__ import annotations

LAYERS: dict[str, tuple[str, ...]] = {
    "unit": (
        "test_agent_runtime.py",
        "test_architecture_boundaries.py",
        "test_artifact.py",
        "test_bm25.py",
        "test_calling.py",
        "test_capacity.py",
        "test_dream.py",
        "test_flush_batches.py",
        "test_gate.py",
        "test_importance.py",
        "test_journal.py",
        "test_layers.py",
        "test_lifecycle.py",
        "test_link.py",
        "test_maintain.py",
        "test_persona.py",
        "test_persona_bootstrap.py",
        "test_persona_injection.py",
        "test_persona_lifecycle_contract.py",
        "test_persona_synthesis.py",
        "test_persona_synthesis_edges.py",
        "test_scope.py",
        "test_seekmemory_context.py",
        "test_store.py",
        "test_strength.py",
        "test_trace.py",
        "test_run_trace.py",
    ),
    "contract": (
        "test_api_contract.py",
        "test_public_interfaces.py",
    ),
    "integration": (
        "test_absorb.py",
        "test_dream_eval.py",
        "test_e2e_kernel.py",
        "test_continuity.py",
        "test_failure_recovery.py",
        "test_group_memory.py",
        "test_privacy_outputs.py",
        "test_persona_long_horizon.py",
        "test_identity_isolation.py",
        "test_lineage_consistency.py",
        "test_migration.py",
        "test_kernel.py",
        "test_recall.py",
        "test_recall_feel.py",
        "test_recall_pipeline.py",
        "test_source_query.py",
        "test_self_impression.py",
        "test_reinforcement.py",
        "test_runtime_actions.py",
        "test_run_recorder.py",
        "test_runtime_scheduler.py",
        "test_runtime_tool_guard.py",
        "test_runtime_adapter.py",
        "test_temporal.py",
        "test_webui.py",
    ),
    "host": (
        "test_webui_host.py",
    ),
    "import": (
        "test_chatlab.py",
        "test_history_import_service.py",
        "test_history_import_store.py",
    ),
    "smoke": (
        "test_package.py",
        "test_eval_harness.py",
        "test_smoke.py",
    ),
}

ALL_LAYERS = ("unit", "contract", "integration", "host", "import", "smoke")


def files_for(layer: str) -> tuple[str, ...]:
    """Return test file names for one layer; all means every mapped test."""
    if layer == "all":
        return tuple(sorted({name for names in LAYERS.values() for name in names}))
    if layer not in LAYERS:
        raise ValueError(f"unknown test layer: {layer}")
    return LAYERS[layer]
