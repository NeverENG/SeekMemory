# perceive: Dialogue Buffering and Extraction

## Responsibility

perceive turns pending dialogue into evidence-checked, family-validated Artifact candidates. Prompts, parsing, topic buffering, importance triage, and model adaptation live here; IngestService owns production database writes.

## Buffer and topics

Buffer is an in-memory view of the Source-backed extraction queue. With a repository, admission persists an immutable Source and extraction_state together; queue state does not duplicate text. Legacy pending.json is kept only for migration and no-repository compatibility.

Topics are built within one session. A user and actual reply are paired through reply_to, and the assistant reply inherits the parent topic. If the parent Source has already been processed, it can be read as pairing context without being queued again. Without a reply relation, a gap over 90 minutes or character-bigram Dice similarity below 0.12 starts a new topic. Topic TTL is an extraction trigger, not a Source-retention deadline.

## Extraction pipeline

1. IngestService selects pending topics, or Dream triage selects higher-value topics.
2. ProviderChatModel maps ChatRequest to the host provider. The extraction prompt requests a structured JSON array and checkable Source IDs.
3. parse_response_checked distinguishes a valid empty array from an empty response or invalid JSON. Invalid responses remain retryable; they are not treated as “nothing to remember.”
4. build_plan validates evidence IDs, resolves subject_id, scope, event time, and strength, deduplicates within a subject/scope boundary, and validates the Artifact family payload.
5. For same-session multi-topic batches, every item must cite evidence from its own single topic in that batch. A behavior memory also needs a valid pair consisting of an assistant Source and its actual user parent.
6. ExtractionPlan returns candidate Artifacts and skip/error information. IngestService performs CAS commits, updates Cache, revises duplicate impressions, and creates similarity/time relations.

## Dream triage and recovery

importance.py uses deterministic rules to rank identity, preference, relationship, plan, privacy boundary, significant event, and user-correction signals. Assistant behavior contributes only when the same topic also has user text; assistant-only topics do not independently trigger model work. This triage is used only by Dream and does not change ordinary nightly/idle FIFO topic selection.

After success, queue rows become extracted. Model or commit failures keep them pending for backoff and retry; exhausted rows become dead for management review. The original Source remains available as evidence.
