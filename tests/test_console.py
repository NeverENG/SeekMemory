"""Public administration projection and persona pack boundaries."""
from __future__ import annotations
import importlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType('_seekmemory_console')
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package

def module(name):
    return importlib.import_module('_seekmemory_console.' + name)

class ConsoleTest(unittest.TestCase):
    def setUp(self):
        self.store = module('store').open_store(':memory:')
        self.addCleanup(self.store.close)
        self.cache = module('store.cache').Cache(self.store.artifacts)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.packs = module('adapters.persona_packs').FilePersonaPacks(ROOT / 'persona_seeds', Path(self.temp.name))
        self.service = module('services.management_service').ManagementService(
            self.store.artifacts, self.store.sources, self.store.ledger, self.cache, None,
            packs=self.packs, dreams=self.store.dreams)

    def seed(self, family, payload, **header):
        art = module('core.artifact').make(family, payload, **header)
        self.store.artifacts.commit(art, expected_revision=0, op='create')
        self.cache.put(art)
        return art

    def test_graph_masks_secret_and_shadow_and_bounds_edges(self):
        self.seed('memory', {'text':'PRIVATE_SENTINEL', 'level':'fact'}, scope='shadow')
        art = self.seed('memory', {'text':'coffee', 'level':'fact'}, subject_id='alice')
        self.seed('memory', {'text':'walk', 'level':'fact'}, subject_id='alice')
        result = self.service.graph()
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.assertTrue(any(e['kind']=='same_subject' for e in result['edges']))
        self.assertEqual(len(self.service.graph(limit=1)['nodes']), 1)
        self.assertNotIn('sources', json.dumps(result))

    def test_impressions_keep_identity_and_scope_separate(self):
        for scope in ['private', 'shadow']:
            self.seed('memory', {'text':'PRIVATE_SENTINEL', 'level':'impression', 'subject_kind':'user'}, subject_id='123', scope=scope)
        self.seed('memory', {'text':'world', 'level':'impression'}, subject_id='world')
        with patch.object(self.store.artifacts, 'list', side_effect=AssertionError('unbounded read')):
            result = self.service.impressions(offset=0, limit=2)
            page = self.service.impressions(offset=2, limit=1)
        self.assertEqual(result['total'], 3)
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(len(page['items']), 1)
        shadow = next(c for c in result['items'] if c['scope']=='shadow')
        self.assertNotIn('PRIVATE_SENTINEL', shadow['summary'])
        with self.assertRaises(ValueError): self.service.impressions(offset=-1)

    def test_graph_reads_recent_snapshot_without_full_library_or_per_node_edges(self):
        from dataclasses import replace
        old = self.seed('memory', {'text': 'old', 'level': 'fact'}, id='old')
        for i in range(1005):
            art = module('core.artifact').make('memory', {'text': f'item-{i}', 'level': 'fact'}, id=f'item-{i:04d}')
            art = replace(art, header=replace(art.header, time=replace(art.header.time, updated='2099-01-01T00:00:00Z')))
            self.store.artifacts.upsert(art)
        self.store.artifacts.add_edge('item-1004', 'item-1003', 'related', 1)
        self.store.artifacts.add_edge('item-1004', old.header.id, 'related', 1)
        for limit in (40, 80, 120):
            with self.subTest(limit=limit), \
                 patch.object(self.store.artifacts, 'list', side_effect=AssertionError('unbounded read')), \
                 patch.object(self.store.artifacts, 'edges_of', side_effect=AssertionError('per-node query')):
                result = self.service.graph(limit=limit)
                self.assertEqual(result['total'], 1006)
                self.assertEqual(result['limit'], limit)
                self.assertEqual(len(result['nodes']), limit)
                self.assertEqual(result['nodes'][0]['id'], 'item-1004')
                self.assertEqual(result['nodes'][-1]['id'], f'item-{1005-limit:04d}')
                self.assertEqual(result['edges'], [{'source': 'item-1004', 'target': 'item-1003', 'kind': 'related'}])
        self.assertEqual(self.store.artifacts.edges_between([], 240), [])
        self.assertEqual(len(self.store.artifacts.edges_between(['item-1004', 'item-1003', old.header.id], 1)), 1)

    def test_dream_projection_excludes_error_bodies(self):
        self.store.dreams.begin('2026-10-25')
        self.store.dreams.finish('2026-10-25', status='failed', errors=['PRIVATE_SENTINEL'], summary={'usage':{'calls':2,'in':100,'out':20}, 'raw':'PRIVATE_SENTINEL'})
        result = self.service.dream_journal()
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.assertEqual(result['items'][0]['calls'], 2)
        self.assertEqual(result['items'][0]['errorCount'], 1)

    def test_install_requires_confirmation_and_stale_revision_fails(self):
        command = {'operation':'install','reference':'official/big_fish','expectedId':None,'expectedRevision':0,'expectedDigest':self.service.pack_detail('official/big_fish')['digest'],'confirmed':True}
        with self.assertRaises(ValueError): self.service.persona_action({**command,'confirmed':False})
        result = self.service.persona_action(command)
        self.assertEqual(result['revision'], 1)
        with self.assertRaises(ValueError): self.service.persona_action(command)
        self.assertEqual(len(self.cache.active('persona')), 1)
        self.assertEqual(self.store.sources.recent_sources(since='',limit=10), [])

    def test_install_rejects_changed_preview_even_when_version_is_reused(self):
        seed = self.packs.read('official/big_fish')
        ref = self.packs.save(seed)
        preview = self.service.pack_detail(ref)
        command = {'operation': 'install', 'reference': ref, 'expectedId': None,
                   'expectedRevision': 0, 'expectedDigest': preview['digest'], 'confirmed': True}
        changed = {**seed, 'persona': 'Changed after preview'}
        (Path(self.temp.name) / 'big_fish.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'pack_changed'):
            self.service.persona_action(command)
        self.assertEqual(self.cache.active('persona'), [])
        self.assertEqual(self.store.ledger.entries(), [])
        command['expectedDigest'] = self.service.pack_detail(ref)['digest']
        result = self.service.persona_action(command)
        self.assertEqual(result['revision'], 1)
        self.assertEqual(self.cache.active('persona')[0].payload['text'], changed['persona'])

    def test_packs_reject_paths_and_builtin_removal(self):
        for ref in ['../secret','official/../../secret','mine/../secret']:
            with self.assertRaises(ValueError): self.packs.read(ref)
        with self.assertRaises(ValueError): self.packs.remove('official/big_fish')
        seed = self.packs.read('official/big_fish')
        ref = self.packs.save(seed)
        with self.assertRaises(ValueError): self.packs.save(seed)
        self.assertEqual(self.packs.read(ref)['id'], seed['id'])
        self.packs.remove(ref)
        with self.assertRaises(LookupError): self.packs.read(ref)

    def test_symlinks_are_rejected_and_catalogue_is_paginated(self):
        path = Path(self.temp.name) / 'big_fish.json'
        path.symlink_to(ROOT / 'docs/examples/persona.big_fish.json')
        with self.assertRaises(ValueError): self.packs.read('mine/big_fish')
        catalogue = self.packs.catalog('official', 0, 1)
        self.assertEqual(len(catalogue['items']), 1)
        self.assertGreaterEqual(catalogue['total'], 2)

    def test_failed_pack_publish_never_leaves_a_partial_file(self):
        seed = self.packs.read('official/big_fish')
        with patch.object(module('adapters.persona_packs').os, 'link', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): self.packs.save(seed)
        self.assertEqual(list(Path(self.temp.name).glob('*.json')), [])
        self.assertEqual(list(Path(self.temp.name).glob('.import-*')), [])

    def test_pack_update_preserves_old_blueprint_and_rejects_stale_version(self):
        seed = self.packs.read('official/big_fish')
        ref = self.packs.save(seed)
        updated = {**seed, 'version':'2.0.0', 'persona':'A new authored blueprint'}
        self.packs.save(updated, seed['version'])
        self.assertEqual(self.packs.read(ref)['version'], '2.0.0')
        backup = next((Path(self.temp.name) / '.trash').glob('*.json'))
        self.assertEqual(json.loads(backup.read_text())['persona'], seed['persona'])
        with self.assertRaises(ValueError): self.packs.save(updated, seed['version'])
        with patch.object(module('adapters.persona_packs').os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): self.packs.save({**updated,'version':'3.0.0'}, '2.0.0')
        self.assertEqual(self.packs.read(ref)['version'], '2.0.0')
        self.assertEqual(list(Path(self.temp.name).glob('.import-*')), [])

    def test_large_graph_is_bounded_and_content_free(self):
        for index in range(1005):
            self.seed('memory', {'level':'fact', 'text':f'entry {index}'}, subject_id='same')
        result=self.service.graph()
        self.assertEqual(len(result['nodes']),120)
        self.assertLessEqual(len(result['edges']),240)
        self.assertEqual(result['total'],1005)
        self.assertTrue(all(e['source']!=e['target'] for e in result['edges']))

    def test_seed_status_reports_provenance_and_matches_contract(self):
        self.service.bootstrap_persona(self.packs.read('official/big_fish'))
        status=module('services.status_service').StatusService(artifacts=self.store.artifacts).persona()
        self.assertEqual(status['seedId'],'big_fish')
        self.assertEqual(status['seedVersion'],'1.0.0')
        self.assertEqual(status['revision'],1)
        self.assertEqual(len(status['revisions']),1)
        self.assertEqual(status['revisions'][0]['sourceIds'],[])

if __name__=='__main__': unittest.main()
