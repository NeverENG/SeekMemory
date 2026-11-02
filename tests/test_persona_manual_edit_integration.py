"""Explicit edits preserve recall, evidence and the single active persona chain."""
from __future__ import annotations

import unittest
from pathlib import Path

from persona_support import PersonaCase
from test_persona_bootstrap import seed_file
from adapters.persona_packs import FilePersonaPacks
from core.artifact import make, revise
from core.bot_behavior import trusted_self_persona
from core.graph import Graph
from maintain.persona import distill_self_persona
from maintain.self_impression import build_self_impressions
from recall.pipeline import build_block
from services.management_service import ManagementService
from services.persona_policy import persona_revision
from app.persona_synthesis import PersonaEvidence
from core.bot_behavior import compose_behaviors


class PersonaManualEditTest(PersonaCase):
    def setUp(self):
        super().setUp()
        packs = FilePersonaPacks(Path(__file__).resolve().parents[1] / 'persona_seeds',
                                 Path(self.temp.name) / 'packs')
        self.service = ManagementService(self.db.artifacts, self.db.sources, self.db.ledger,
                                         self.cache, None, packs=packs)
        ref = packs.save(seed_file())
        self.service.persona_action({'operation': 'install', 'reference': ref,
            'expectedId': None, 'expectedRevision': 0,
            'expectedDigest': self.service.pack_detail(ref)['digest'], 'confirmed': True})

    def recall(self):
        return build_block(self.cache, Graph(self.db.artifacts), self.db.artifacts, self.db.sources,
                           'owner', '你好', True, {'explore_rate': 0, 'budget_chars': 2000}.get,
                           'owner', speaker='owner', dry_run=True)

    def grow(self):
        self.three()
        build_self_impressions(self.db.artifacts, self.db.sources, self.cache)
        return distill_self_persona(self.db.artifacts, self.db.sources, self.cache)

    def edit(self, current, payload, scope=None):
        self.service.update({'id': current.header.id, 'expectedRevision': current.header.revision,
            'payload': payload, 'scope': scope or current.header.scope, 'state': 'active',
            'reason': 'Explicit authored settings', 'confirmed': True})
        return self.cache.get(current.header.id)

    def test_growth_then_text_edit_remains_recalled_and_preserves_evidence(self):
        grown = self.grow()
        self.assertTrue(trusted_self_persona(grown))
        before_sources = self.db.sources.recent_sources(since='', limit=100)
        application = grown.payload['pack_application']
        text = '你是手工修改后的星灯，先听完再给出具体建议。'
        # Also accepts the payload produced by the previous UI, without retaining its broken text relation.
        edited = self.edit(grown, {**grown.payload, 'text': text, 'base_text': text})
        self.assertEqual(edited.header.id, grown.header.id)
        self.assertEqual(edited.header.revision, 3)
        self.assertEqual(edited.payload['text'], text)
        self.assertEqual(edited.payload['origin'], 'seed')
        self.assertEqual(edited.header.said_by, 'seed')
        self.assertEqual(edited.payload['pack_application'], application)
        self.assertEqual(edited.header.lineage, grown.header.lineage)
        self.assertEqual(self.db.sources.recent_sources(since='', limit=100), before_sources)
        self.assertTrue(trusted_self_persona(edited))
        block, info = self.recall()
        self.assertIn(text, block)
        self.assertIn(edited.header.id, info['final_ids'])
        self.assertNotIn('许澄', block)
        history = self.db.artifacts.history(edited.header.id)
        self.assertEqual([row['revision'] for row in history], [1, 2, 3])
        self.assertEqual(history[1]['payload'], grown.payload)
        grown_again = distill_self_persona(self.db.artifacts, self.db.sources, self.cache)
        self.assertTrue(trusted_self_persona(grown_again))
        self.assertEqual(grown_again.payload['base_text'], text)
        self.service.rollback_persona({'id': grown.header.id, 'revision': 2,
            'reason': 'Restore actual growth revision', 'confirmed': True})
        self.assertEqual(self.cache.get(grown.header.id).payload, grown.payload)
        self.assertTrue(trusted_self_persona(self.cache.get(grown.header.id)))
        self.assertTrue(self.db.ledger.verify())

    def commit_revision(self, current, revision):
        self.db.artifacts.commit(revision, expected_revision=current.header.revision,
            op='revise', source_ids=revision.header.lineage.sources)
        self.cache.put(revision)
        return revision

    def test_synthesized_growth_text_edit_is_authored_and_recalled(self):
        grown = self.grow()
        synthesized = self.commit_revision(grown, persona_revision(grown,
            {'persona': '你会耐心倾听并提供建议。', 'style': {}, 'boundaries': ['保护隐私'],
             'change_reason': 'Evidence-backed synthesis'},
            [PersonaEvidence(id=ref, kind='self_impression', text='Public behavior',
                             source_ids=grown.header.lineage.sources)
             for ref in grown.header.lineage.derived_from]))
        self.assertTrue(trusted_self_persona(synthesized))
        edited = self.edit(synthesized, {**synthesized.payload, 'text': '你会先问对方需要什么帮助。'})
        self.assertTrue(trusted_self_persona(edited))
        self.assertEqual(edited.header.said_by, 'seed')
        self.assertNotIn('synthesis', edited.payload)
        self.assertEqual(edited.header.lineage, synthesized.header.lineage)
        self.assertIn(edited.header.id, self.recall()[1]['final_ids'])
        self.assertEqual(self.db.artifacts.history(edited.header.id)[-2]['payload'], synthesized.payload)

    def test_legacy_behavior_persona_can_be_explicitly_authored_without_guessing_a_pack(self):
        grown = self.grow()
        legacy = self.commit_revision(grown, revise(grown, payload={
            'text': compose_behaviors(grown.payload['behaviors']),
            'behaviors': grown.payload['behaviors']}))
        self.assertTrue(trusted_self_persona(legacy))
        edited = self.edit(legacy, {**legacy.payload, 'text': '你会认真听完对方的话。'})
        self.assertTrue(trusted_self_persona(edited))
        self.assertNotIn('pack_application', edited.payload)
        self.assertEqual(edited.payload['seed_id'], legacy.header.id)
        self.assertIn(edited.header.id, self.recall()[1]['final_ids'])

    def test_unsafe_headers_never_gain_authored_trust(self):
        grown = self.grow()
        for changes in ({'scope': 'shadow'}, {'scope': 'private'},
                        {'subject_id': 'another-person'}, {'shareable': 'secret'}):
            unsafe = self.seed(make('persona', dict(grown.payload),
                subject_id=changes.get('subject_id', grown.header.subject_id),
                scope=changes.get('scope', grown.header.scope),
                shareable=changes.get('shareable', grown.header.shareable),
                said_by='inferred', lineage=grown.header.lineage, strength=grown.header.strength))
            edited = self.edit(unsafe, {**unsafe.payload, 'text': 'PRIVATE_SENTINEL'})
            self.assertFalse(trusted_self_persona(edited))
            self.assertNotEqual(edited.header.said_by, 'seed')
            self.assertNotIn(edited.header.id, self.recall()[1]['final_ids'])
        self.assertNotIn('PRIVATE_SENTINEL', self.recall()[0])

    def test_name_only_edit_keeps_the_growth_provenance_and_remains_recalled(self):
        grown = self.grow()
        edited = self.edit(grown, {**grown.payload, 'persona_name': '新名字'})
        self.assertEqual(edited.payload['origin'], 'dream')
        self.assertEqual(edited.payload['base_text'], grown.payload['base_text'])
        self.assertEqual(edited.payload['behaviors'], grown.payload['behaviors'])
        self.assertTrue(trusted_self_persona(edited))
        self.assertIn(edited.header.id, self.recall()[1]['final_ids'])

    def test_manual_edit_does_not_grant_trust_to_unsafe_personas(self):
        for scope in ('shared', 'shadow', 'private'):
            with self.subTest(scope=scope):
                unsafe = self.seed(make('persona', {'text': 'PRIVATE_SENTINEL'}, scope=scope))
                edited = self.edit(unsafe, {'text': 'Changed PRIVATE_SENTINEL'})
                self.assertFalse(trusted_self_persona(edited))
                self.assertNotIn(edited.header.id, self.recall()[1]['final_ids'])
        grown = self.grow()
        shadow = self.edit(grown, {**grown.payload, 'text': 'PRIVATE_SENTINEL'}, scope='shadow')
        self.assertFalse(trusted_self_persona(shadow))
        self.assertNotIn('PRIVATE_SENTINEL', self.recall()[0])


if __name__ == '__main__':
    unittest.main()
