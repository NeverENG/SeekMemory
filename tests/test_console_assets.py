"""Complete persona packs preserve authored assets without entering chat evidence."""
from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_console import module, ROOT
from persona_pack_fixture import pack, png


class PackAssetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.adapter = module('adapters.persona_packs').FilePersonaPacks(ROOT / 'persona_seeds', self.path)
        self.seed = self.adapter.read('official/big_fish')

    def test_legacy_seed_and_complete_pack_survive_restart_update_and_remove(self):
        ref = self.adapter.save(self.seed)
        self.assertEqual(self.adapter.bundle(ref)['artwork'], None)
        complete = pack({**self.seed, 'version': '2'})
        self.adapter.save(complete, self.seed['version'])
        reopened = type(self.adapter)(ROOT / 'persona_seeds', self.path)
        result = reopened.bundle(ref)
        self.assertEqual(result, complete)
        self.assertTrue(reopened.catalog('mine')['items'][0]['artworkRef'].startswith(ref + '@'))
        self.assertEqual(reopened.read(ref), complete['seed'])
        self.assertEqual(reopened.artwork(ref), complete['artwork'])
        backup = list((self.path / '.trash').glob('*.json'))
        self.assertEqual(len(backup), 1)
        self.assertEqual(json.loads(backup[0].read_text())['version'], self.seed['version'])
        reopened.remove(ref)
        self.assertEqual(reopened.catalog('mine')['total'], 0)
        archived = [json.loads(p.read_text()) for p in (self.path / '.trash').glob('*.json')]
        self.assertIn(complete, archived)
        reopened.save(complete)
        self.assertEqual(reopened.bundle(ref), complete)

    def test_invalid_asset_or_failed_update_preserves_previous_complete_pack(self):
        complete = pack(self.seed)
        ref = self.adapter.save(complete)
        for artwork in [
            {'mediaType': 'image/svg+xml', 'dataBase64': 'PHN2Zz4='},
            {'mediaType': 'image/png', 'dataBase64': 'not_base64'},
            {'mediaType': 'image/png', 'dataBase64': base64.b64encode(png()[:-1]).decode()},
            {'mediaType': 'image/png', 'dataBase64': 'a' * 2796208},
            {'path': '../../private.png'},
        ]:
            with self.subTest(artwork=str(artwork)[:80]):
                with self.assertRaises(ValueError):
                    self.adapter.save({**complete, 'seed': {**self.seed, 'version': '2'}, 'artwork': artwork}, self.seed['version'])
                self.assertEqual(self.adapter.bundle(ref), complete)
        with patch.object(module('adapters.persona_packs').os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.adapter.save({**complete, 'seed': {**self.seed, 'version': '2'}}, self.seed['version'])
        self.assertEqual(self.adapter.bundle(ref), complete)
        self.assertEqual(list(self.path.glob('.import-*')), [])

    def test_missing_license_unknown_fields_and_path_traversal_are_rejected(self):
        complete = pack(self.seed)
        for raw in [{**complete, 'licenseText': ''}, {**complete, 'format': 'v99'},
                    {**complete, 'sources': ['private']}, {**complete, 'seed': {**self.seed, 'id': '../escape'}},
                    {**complete, 'seed': {**self.seed, 'source': ''}}]:
            with self.assertRaises(ValueError): self.adapter.save(raw)
        for ref in ['mine/../secret', 'official/../../a', 'mine/file.png', '/etc/passwd']:
            with self.assertRaises((ValueError, LookupError)): self.adapter.artwork(ref)
        self.assertEqual(self.adapter.catalog('mine')['total'], 0)

    def test_install_rejects_license_or_artwork_changed_after_preview(self):
        store = module('store').open_store(':memory:')
        self.addCleanup(store.close)
        cache = module('store.cache').Cache(store.artifacts)
        service = module('services.management_service').ManagementService(
            store.artifacts, store.sources, store.ledger, cache, None, packs=self.adapter)
        complete = pack(self.seed)
        ref = self.adapter.save(complete)
        preview = service.pack_detail(ref)
        path = self.path / (self.seed['id'] + '.json')
        path.write_text(json.dumps({**complete, 'licenseText': 'Changed license'}))
        with self.assertRaisesRegex(ValueError, 'pack_changed'):
            service.persona_action({'operation': 'install', 'reference': ref,
                'expectedId': None, 'expectedRevision': 0,
                'expectedDigest': preview['digest'], 'confirmed': True})
        self.assertEqual(cache.active('persona'), [])
        self.assertEqual(store.ledger.entries(), [])

    def test_png_is_bounded_and_metadata_is_not_exported(self):
        validate = module('core.persona_artwork').validate_artwork
        self.assertEqual(validate(png(metadata=True)), png())
        for data in [b'', png() + b'payload', png(width=2049), png()[:-1], b'not a png']:
            with self.assertRaises(ValueError): validate(data)
        corrupt = bytearray(png()); corrupt[-5] ^= 1
        with self.assertRaises(ValueError): validate(bytes(corrupt))

    def test_official_artwork_is_local_readonly_and_rejects_symlinks(self):
        official = self.path / 'official'
        directory = official / self.seed['id']; directory.mkdir(parents=True)
        (official / 'index.json').write_text(json.dumps([self.seed['id']]))
        (directory / 'persona.json').write_text(json.dumps(self.seed))
        (directory / 'LICENSE').write_text('CC0 fixture')
        (directory / 'artwork.png').write_bytes(png())
        adapter = type(self.adapter)(official, self.path / 'mine')
        self.assertIsNotNone(adapter.catalog('official')['items'][0]['artworkRef'])
        (directory / 'artwork.png').unlink()
        (directory / 'artwork.png').symlink_to(ROOT / 'LICENSE-MIT')
        with self.assertRaises(ValueError): adapter.bundle('official/' + self.seed['id'])


if __name__ == '__main__': unittest.main()
