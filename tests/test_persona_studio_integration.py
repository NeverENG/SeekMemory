"""Persona authoring keeps explicit baselines, history and authored assets separate."""
from __future__ import annotations

import base64
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import test_console as console_support
module = console_support.module
from persona_pack_fixture import pack, png


class PersonaStudioTest(unittest.TestCase):
    setUp = console_support.ConsoleTest.setUp

    def install(self, reference):
        current = self.cache.active("persona")
        base = current[0] if current else None
        return self.service.persona_action({"operation": "install", "reference": reference,
            "expectedId": base.header.id if base else None,
            "expectedRevision": base.header.revision if base else 0,
            "expectedDigest": self.service.pack_detail(reference)["digest"], "confirmed": True})

    def status(self):
        return module('services.status_service').StatusService(artifacts=self.store.artifacts).persona()

    def test_namespaced_baseline_survives_edit_restart_pack_update_and_rollback(self):
        seed = self.packs.read('official/big_fish')
        ref = self.packs.save(pack({**seed, 'persona': 'Different personal settings'}))
        result = self.install('official/big_fish')
        baseline = self.status()['packApplication']
        self.assertEqual(baseline['reference'], 'official/big_fish')
        self.assertEqual(baseline['settingsDigest'], baseline['currentSettingsDigest'])
        current = self.store.artifacts.get(result['id'])
        payload = {**current.payload, 'text': 'Edited current persona', 'custom_metadata': {'keep': True}}
        command = {'id': current.header.id, 'expectedRevision': current.header.revision,
            'payload': payload, 'scope': current.header.scope, 'state': 'active', 'reason': 'Edit persona', 'confirmed': True}
        self.service.update(command)
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            self.service.update(command)
        self.assertNotEqual(self.status()['packApplication']['currentSettingsDigest'], baseline['settingsDigest'])
        self.assertEqual(self.status()['packApplication']['reference'], 'official/big_fish')
        target = self.service.pack_lookup(ref)
        self.service.persona_action({'operation': 'importPack', 'pack': {**target['pack'], 'seed': {**target['pack']['seed'], 'version': '2'}},
            'expectedVersion': seed['version'], 'expectedDigest': target['digest'], 'confirmed': True})
        self.assertEqual(self.store.artifacts.get(result['id']).payload, payload)
        self.cache.load()
        self.assertEqual(self.status()['packApplication']['reference'], 'official/big_fish')
        restored = self.service.rollback_persona({'id': result['id'], 'revision': 1, 'reason': 'Restore baseline', 'confirmed': True})
        self.assertEqual(restored['id'], result['id'])
        self.assertEqual(restored['revision'], 3)
        self.assertEqual(self.status()['packApplication'], baseline)
        self.assertEqual(len(self.store.artifacts.history(result['id'])), 3)
        self.assertEqual(self.store.sources.recent_sources(since='', limit=100), [])
        self.assertTrue(self.store.ledger.verify())

    def test_legacy_provenance_is_unknown_and_management_cannot_forge_an_association(self):
        seed = self.packs.read('official/big_fish')
        result = self.service.bootstrap_persona(seed)
        self.assertIsNone(self.status()['packApplication'])
        self.install('official/big_fish')
        current = self.store.artifacts.get(result['id'])
        payload = dict(current.payload)
        payload.pop('pack_application')
        with self.assertRaises(ValueError):
            self.service.update({'id': result['id'], 'expectedRevision': current.header.revision,
                'payload': payload, 'scope': current.header.scope, 'state': 'active', 'reason': 'Forge', 'confirmed': True})
        self.assertEqual(self.store.artifacts.get(result['id']), current)

    def test_lookup_finds_pack_beyond_first_page_and_digest_conflicts_leave_content_intact(self):
        seed = self.packs.read('official/big_fish')
        for index in range(30):
            self.packs.save({**seed, 'id': f'pack-{index:02d}'})
        page = self.service.pack_catalog('mine')
        self.assertEqual(len(page['items']), 24)
        target = self.service.pack_lookup('mine/pack-29')
        self.assertIsNotNone(target['pack'])
        self.assertEqual(self.service.pack_lookup('mine/absent'), {'pack': None, 'digest': None})
        edited = {**target['pack'], 'seed': {**target['pack']['seed'], 'version': '2'}}
        # An external edit that reuses a version is still detected.
        path = Path(self.temp.name) / 'pack-29.json'
        path.write_text(json.dumps({**target['pack'], 'licenseText': 'Changed without version bump'}))
        with self.assertRaisesRegex(ValueError, 'pack_changed'):
            self.service.persona_action({'operation': 'importPack', 'pack': edited,
                'expectedVersion': seed['version'], 'expectedDigest': target['digest'], 'confirmed': True})
        self.assertEqual(self.packs.bundle('mine/pack-29')['licenseText'], 'Changed without version bump')
        self.assertEqual(self.cache.active('persona'), [])

    def test_competing_pack_updates_publish_only_one_reviewed_version(self):
        seed = self.packs.read('official/big_fish')
        ref = self.packs.save(seed)
        digest = self.service.pack_detail(ref)['digest']
        def update(version):
            try:
                self.packs.save({**seed, 'version': version}, seed['version'], expected_digest=digest)
                return 'saved'
            except ValueError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(update, ['2', '3']))
        self.assertCountEqual(outcomes, ['saved', 'conflict'])
        self.assertEqual(len(list((Path(self.temp.name) / '.trash').glob('*.json'))), 1)

    def test_artwork_is_pinned_and_removed_or_changed_pack_never_substitutes_a_cover(self):
        seed = self.packs.read('official/big_fish')
        complete = pack(seed)
        ref = self.packs.save(complete)
        self.install(ref)
        baseline = self.status()['packApplication']
        self.assertEqual(self.service.pack_artwork(ref, baseline['artworkDigest']), complete['artwork'])
        current = self.cache.active('persona')[0]
        # License-only updates do not change persona settings or the verified image.
        updated = {**complete, 'seed': {**seed, 'version': '2'}, 'licenseText': 'Updated attribution'}
        self.packs.save(updated, seed['version'])
        self.assertEqual(self.service.pack_artwork(ref, baseline['artworkDigest']), complete['artwork'])
        art = {'mediaType': 'image/png', 'dataBase64': base64.b64encode(png(width=3)).decode()}
        self.packs.save({**updated, 'seed': {**seed, 'version': '3'}, 'artwork': art}, '2')
        with self.assertRaisesRegex(ValueError, 'pack_changed'):
            self.service.pack_artwork(ref, baseline['artworkDigest'])
        self.packs.remove(ref)
        with self.assertRaises(LookupError):
            self.service.pack_artwork(ref, baseline['artworkDigest'])
        self.assertEqual(self.cache.active('persona')[0], current)
        # A same-ID official pack is never used as a substitute.
        self.assertEqual(self.status()['packApplication']['reference'], ref)

    def test_both_growth_policies_keep_the_installed_baseline(self):
        self.install('official/big_fish')
        current = self.cache.active('persona')[0]
        policy = module('services.persona_policy')
        draft = {'persona': 'A grown persona', 'style': {'tone': 'warm'}, 'boundaries': ['privacy'], 'change_reason': 'Growth'}
        evolved = policy.persona_revision(current, draft, [])
        self.assertEqual(evolved.payload['pack_application'], current.payload['pack_application'])
        behavior = module('core.artifact').make('memory', {'text': 'Behavior', 'bot_behavior': 'admit_uncertainty', 'level': 'impression'})
        deterministic = module('maintain.persona_policy').prepare_persona([behavior], [current]).persona
        self.assertEqual(deterministic.payload['pack_application'], current.payload['pack_application'])


if __name__ == '__main__':
    unittest.main()
