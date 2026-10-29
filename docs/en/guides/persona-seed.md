# Persona Seed Files

A persona seed is authored configuration used to initialize the single bot:self Persona Artifact chain. It is not a Source, chat evidence, or a second runtime profile. Validation and mapping live in core/persona.py; ManagementService.bootstrap_persona performs the admin write.

## JSON format

The required fields are id, version, name, and persona. The other fields are optional:

    {
      "id": "big_fish",
      "version": "1.0.0",
      "name": "Big Fish",
      "persona": "You are Big Fish: gentle, with a slightly stubborn edge.",
      "style": {"tone": "gentle but stubborn", "sentence_length": "short"},
      "boundaries": ["Do not invent user history", "Do not expose private Source text"],
      "corpus": [],
      "license": "CC0-1.0",
      "source": "original",
      "content_rating": "general",
      "locale": "en-US"
    }

Validation rules:

- id is 2–64 lowercase letters, digits, dots, underscores, or hyphens; the first character must be a letter or digit.
- version must be non-empty and at most 32 characters; name at most 80; persona at most 20,000 characters.
- persona_text is accepted as a compatibility alias for early seed files. Use persona in new files.
- style must be a JSON-serializable object of at most 20,000 characters. boundaries may contain up to 32 items, each at most 300 characters.
- corpus is optional. If present, it needs at least 12 user/assistant pairs and 1,200 total dialogue characters, with at most 128 pairs. Each field is at most 2,000 characters and total JSON is at most 50,000 characters. Entries may contain only user and assistant.
- Unknown fields are rejected rather than silently accepted.

Valid examples: [persona.big_fish.json](../../examples/persona.big_fish.json) and [persona.tsundere_ojou.json](../../examples/persona.tsundere_ojou.json). If there is no substantial corpus, omit it and provide a usable persona text directly.

## Validate, then write

From the repository root:

    python3 scripts/bootstrap_persona.py --db /path/to/memory.db --file docs/examples/persona.big_fish.json --dry-run
    python3 scripts/bootstrap_persona.py --db /path/to/memory.db --file docs/examples/persona.big_fish.json

Dry-run validates the file and prints seed ID, version, corpus count, and persona character count without opening the database for writes. A normal run creates or revises the same Persona Artifact chain, writes seed provenance, and consolidates duplicate active persona heads in one commit_many transaction.

The seed header uses subject_id=bot:self, scope=shared, shareable=public, and said_by=seed. Bootstrap creates no Source, starts no extraction, and makes no model call. If supplied, corpus is kept on the one-time bootstrap revision as authored source material; later evolution keeps corpus_count/hash and does not inject corpus into chat recall or treat it as raw evidence.

## Later evolution and rollback

Periodic maintenance uses the current persona, qualified shared self-impressions, and bounded shared-memory summaries as synthesis input. Private raw Sources are not sent to the synthesis model; one Dream cycle performs at most one bounded persona synthesis. New content becomes an appended revision on the same Persona ID with evidence lineage. Unchanged output or a failed call keeps the current revision.

The management UI can roll back to historical content by creating a new version. Existing revisions are never overwritten or deleted. Do not create parallel Persona Artifacts by editing a second persona record.

## Portable packs with artwork

Legacy seed JSON remains readable without migration. A complete `.seekmemory.json` file wraps the canonical seed; artwork is never added to the Persona Artifact:

```json
{
  "format": "seekmemory.persona-pack/v1",
  "seed": {"id": "my-persona", "version": "1", "name": "Example", "persona": "Authored persona", "license": "CC0-1.0", "source": "original"},
  "licenseText": "Full license covering both the persona and artwork",
  "artwork": null
}
```

Artwork uses `{"mediaType":"image/png","dataBase64":"…"}`, never filesystem paths or remote URLs. Limits: 3 MiB per complete pack, 64 KiB per seed, 64 KiB UTF-8 license text, and 2 MiB per image. Images must be static, 8-bit, non-interlaced PNG, at most 2048 pixels per dimension and 4 million pixels total. Validation checks signatures, chunk CRCs, bounded pixel decompression and row filters, and strips ancillary metadata. Convert other formats before importing.

A pack containing artwork requires nonempty seed license/source and licenseText. The license must cover the artwork. Structural checks do not replace author review of rights and content.

In My Packs, import either legacy JSON or a complete pack, optionally add/replace artwork and fill the license, then confirm saving. Import never installs automatically; installation requires separate confirmation. Preview offers seed-only and complete-pack exports. Packs exclude raw Sources, evidence and runtime state; users must still inspect persona prose before sharing.

Personal files remain at `persona_packs/<id>.json`, containing either a legacy seed or the new envelope. Updates require the previous version and a different new version, back up the old file in `.trash`, and publish the complete replacement atomically. Removal moves the file to `.trash` without changing the active persona. Reimport a backup to restore it. Before rolling back code, export seed-only JSON: older code cannot read the new envelope, while the database and installed persona remain unaffected.

Built-in packs still contain `persona_seeds/<id>/persona.json` and `LICENSE`, with optional `artwork.png`. Track these assets in Git; packaging validates and includes them. Unsupported files, damaged/empty/oversized images and symlinks block packaging. Missing or unreadable artwork falls back to the first character of the pack name.
