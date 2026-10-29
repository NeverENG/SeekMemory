"""Local persona files; authored seeds never become chat evidence."""
from __future__ import annotations

import json
import os
import tempfile
import re
import base64
import hashlib
from pathlib import Path

from ..core.persona_pack import normalize_pack, PACK_FORMAT, MAX_PACK_BYTES
from ..core.persona_artwork import MAX_ARTWORK_BYTES, validate_artwork

ID = re.compile(r'^[a-z0-9][a-z0-9_.-]{1,63}$')
MAX_BYTES = 65536


class FilePersonaPacks:
    def __init__(self, official: Path, personal: Path) -> None:
        self.official = official
        self.personal = personal

    def _path(self, reference: str) -> Path:
        parts = reference.split('/')
        if len(parts) != 2 or parts[0] not in {'official', 'mine'} or not ID.fullmatch(parts[1]):
            raise ValueError('人格包标识无效')
        root = self.official if parts[0] == 'official' else self.personal
        path = root / parts[1] / 'persona.json' if parts[0] == 'official' else root / (parts[1] + '.json')
        if root.is_symlink() or path.parent.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('人格包不允许符号链接或目录穿越')
        return path

    @staticmethod
    def _read_json(path: Path, limit: int = MAX_BYTES) -> object:
        if not path.is_file():
            raise LookupError('人格包不存在')
        if path.stat().st_size > limit:
            raise ValueError('人格文件过大')
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('人格文件过大')
        return json.loads(raw.decode('utf-8'))

    def bundle(self, reference: str) -> dict:
        path = self._path(reference)
        bundle = normalize_pack(self._read_json(path, MAX_PACK_BYTES))
        if bundle['seed']['id'] != reference.split('/')[1]:
            raise ValueError('人格包目录与文件 id 不一致')
        if reference.startswith('official/'):
            license_path = path.parent / 'LICENSE'
            if license_path.is_symlink() or not license_path.is_file() or not 0 < license_path.stat().st_size <= MAX_BYTES:
                raise ValueError('人格包许可证缺失或无效')
            bundle['licenseText'] = license_path.read_text(encoding='utf-8')
            artwork_path = path.parent / 'artwork.png'
            if artwork_path.is_symlink():
                raise ValueError('封面不允许符号链接')
            if artwork_path.exists():
                if not artwork_path.is_file() or not 0 < artwork_path.stat().st_size <= MAX_ARTWORK_BYTES:
                    raise ValueError('封面文件大小无效')
                data = validate_artwork(artwork_path.read_bytes())
                bundle['artwork'] = {'mediaType': 'image/png', 'dataBase64': base64.b64encode(data).decode('ascii')}
        return normalize_pack(bundle)

    def read(self, reference: str) -> dict:
        return self.bundle(reference)['seed']

    def artwork(self, reference: str) -> dict:
        artwork = self.bundle(reference)['artwork']
        if artwork is None:
            raise LookupError('人格包没有封面')
        return artwork

    @staticmethod
    def artwork_ref(reference: str, bundle: dict) -> str | None:
        if bundle['artwork'] is None:
            return None
        digest = hashlib.sha256(bundle['artwork']['dataBase64'].encode('ascii')).hexdigest()
        return reference + '@' + digest

    def catalog(self, collection: str, offset: int = 0, limit: int = 24) -> dict:
        if collection not in {'official', 'mine'} or not 0 <= offset <= 100000 or not 1 <= limit <= 100:
            raise ValueError('目录分页参数无效')
        if collection == 'official':
            index = self.official / 'index.json'
            if index.is_symlink():
                raise ValueError('目录索引不允许符号链接')
            ids = self._read_json(index)
            if not isinstance(ids, list) or any(not isinstance(i, str) or not ID.fullmatch(i) for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('人格包目录索引无效')
        else:
            if self.personal.is_symlink():
                raise ValueError('个人目录不允许符号链接')
            ids = sorted(p.stem for p in self.personal.glob('*.json'))
        items = []
        for seed_id in ids[offset:offset + limit]:
            reference = f'{collection}/{seed_id}'
            bundle = self.bundle(reference)
            seed = bundle['seed']
            items.append({
                'reference': reference, 'id': seed['id'], 'name': seed['name'],
                'version': seed['version'], 'description': seed['persona'][:120],
                'license': seed['license'], 'source': seed['source'],
                'contentRating': seed['content_rating'], 'locale': seed['locale'],
                'artworkRef': self.artwork_ref(reference, bundle),
            })
        return {'items': items, 'total': len(ids), 'offset': offset, 'limit': limit}

    def save(self, raw: dict, expected_version: str | None = None) -> str:
        bundle = normalize_pack(raw)
        seed = bundle['seed']
        reference = f"mine/{seed['id']}"
        path = self._path(reference)
        if expected_version is not None:
            previous = self.read(reference)
            if previous['version'] != expected_version or seed['version'] == expected_version:
                raise ValueError('人格包版本已变化，或新文件尚未提高版本号')
        stored = bundle if isinstance(raw, dict) and raw.get('format') == PACK_FORMAT else seed
        encoded = json.dumps(stored, ensure_ascii=False, indent=2).encode('utf-8')
        if len(encoded) > MAX_PACK_BYTES:
            raise ValueError('人格文件过大')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Publish only a complete file, without overwriting a concurrent import.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.import-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if expected_version is None:
                os.link(temporary, path)
            else:
                # Keep the old blueprint recoverable before atomically publishing the update.
                trash = self.personal / '.trash'
                if trash.is_symlink():
                    raise ValueError('回收目录无效')
                trash.mkdir(exist_ok=True)
                from uuid import uuid4
                os.link(path, trash / f'{path.stem}-{uuid4().hex}.json')
                os.replace(temporary, path)
        except FileExistsError as exc:
            raise ValueError('同名人格包已存在，请使用新的 id') from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return reference

    def remove(self, reference: str) -> None:
        if not reference.startswith('mine/'):
            raise ValueError('内置人格包不可移除')
        path = self._path(reference)
        if not path.exists():
            raise LookupError('人格包不存在')
        # Keep a recoverable local copy. Removing a pack never changes active persona.
        trash = self.personal / '.trash'
        if trash.is_symlink():
            raise ValueError('回收目录无效')
        trash.mkdir(exist_ok=True)
        from uuid import uuid4
        path.rename(trash / f'{path.stem}-{uuid4().hex}.json')
