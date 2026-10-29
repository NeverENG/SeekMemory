"""Validate tracked authored persona files before packaging; no storage or model calls.

打包前校验已跟踪人工人格文件，不调用存储或模型。
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def seed_files(root: Path, tracked: set[str]) -> set[str]:
    """Return the approved tracked seed files; reject unsafe paths, formats or missing licenses.

    返回认可的已跟踪设定文件，拒绝不安全路径、格式或缺少许可。
    """
    import sys
    # Same repository validator used at runtime; no alternative seed schema.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.persona import normalize_persona_file
    from core.persona_artwork import MAX_ARTWORK_BYTES, validate_artwork

    directory = root / 'persona_seeds'
    index = directory / 'index.json'
    if directory.is_symlink() or index.is_symlink() or not index.is_file():
        raise ValueError('人格目录或索引缺失/不安全')
    if not 0 < index.stat().st_size <= 65536:
        raise ValueError('人格目录索引大小无效')
    ids = json.loads(index.read_text(encoding='utf-8'))
    if not isinstance(ids, list) or any(not isinstance(i, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,63}', i) for i in ids) or len(ids) != len(set(ids)):
        raise ValueError('人格目录索引无效')
    files = {'persona_seeds/index.json'}
    for seed_id in ids:
        pack = directory / seed_id
        if pack.is_symlink() or not pack.is_dir():
            raise ValueError('人格包目录缺失/不安全')
        names = {path.name for path in pack.iterdir()}
        if not {'persona.json', 'LICENSE'} <= names:
            raise ValueError('人格包缺少文件或许可')
        for path in pack.iterdir():
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError('人格包包含不安全资源')
            if path.name not in {'persona.json', 'LICENSE', 'artwork.png'}:
                raise ValueError('人格包包含不支持的资源；封面仅支持 artwork.png')
            if not 0 < path.stat().st_size <= (MAX_ARTWORK_BYTES if path.name == 'artwork.png' else 65536):
                raise ValueError('人格包资源为空或过大')
            if path.name == 'artwork.png':
                validate_artwork(path.read_bytes())
            if path.name == 'LICENSE' and not path.read_text(encoding='utf-8').strip():
                raise ValueError('人格包许可证为空')
            files.add(path.relative_to(root).as_posix())
        seed = normalize_persona_file(json.loads((pack / 'persona.json').read_text(encoding='utf-8')))
        if seed['id'] != seed_id or not seed['license'] or not seed['source']:
            raise ValueError('人格包 id、许可或来源无效')
    if not files <= tracked:
        raise ValueError('人格包资源必须由 Git 跟踪')
    return files
