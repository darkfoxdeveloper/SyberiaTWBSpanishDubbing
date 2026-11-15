"""Read the verified audio, project catalogue and approval records used by the exporter."""

from collections import defaultdict
from contextlib import closing
from hashlib import file_digest, sha256
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
from struct import unpack_from

from syberia_scan import BANK_DIR, ENGLISH

MANIFEST = 'manifest_syberia.json'
ENGLISH_BANKS = PurePosixPath((BANK_DIR / ENGLISH).as_posix())


def wem_metadata(blob):
    """Return frame count, channels and sample rate for Syberia's Wwise Vorbis."""
    if (len(blob) < 12 or blob[:4] != b'RIFF' or blob[8:12] != b'WAVE'
            or unpack_from('<I', blob, 4)[0] + 8 != len(blob)):
        raise ValueError('El recurso no es un WEM RIFF completo.')
    info = None
    has_audio = False
    offset = 12
    while offset + 8 <= len(blob):
        tag, length = unpack_from('<4sI', blob, offset)
        start = offset + 8
        offset = start + length
        if offset > len(blob):
            raise ValueError('El WEM contiene un bloque truncado.')
        if tag == b'fmt ':
            if length != 0x42 or unpack_from('<H', blob, start)[0] != 0xFFFF:
                raise ValueError('El WEM no usa el formato Vorbis de Syberia.')
            channels, rate = unpack_from('<HI', blob, start + 2)
            frames = unpack_from('<I', blob, start + 0x18)[0]
            info = frames, channels, rate
        elif tag == b'data':
            has_audio = length > 0
    if offset != len(blob) or not info or not all(info) or not has_audio:
        raise ValueError('El WEM carece de audio o de sus metadatos.')
    return info


def file_sha(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def hash_bytes(blob):
    return sha256(blob).hexdigest()


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def confined(root, relative):
    relative = Path(relative)
    path = root / relative
    if relative.anchor or '..' in relative.parts or path.resolve() != path:
        raise ValueError(f'Ruta de datos o de banco inválida: {relative}')
    return path


def load_manifest(data):
    path = confined(data, MANIFEST)
    if not path.is_file():
        raise ValueError('Abre el doblaje de Syberia para preparar su catálogo.')
    manifest = load_json(path)
    if manifest.get('version') != 1 or manifest.get('game_id') != 'syberia':
        raise ValueError('El catálogo de doblaje de Syberia no es compatible.')

    banks = manifest['banks']
    entries = manifest['entries']
    slots = defaultdict(list)
    paths = set()
    for name, bank in banks.items():
        relative = PurePosixPath(name)
        if (relative.parent != ENGLISH_BANKS or relative.as_posix() != name
                or re.fullmatch(r'[A-Za-z0-9_-]+_Dialog\.bnk', relative.name) is None
                or name.casefold() in paths
                or type(bank.get('size')) is not int or bank['size'] <= 0
                or not valid_hash(bank.get('sha256'))):
            raise ValueError(f'Banco inválido en el catálogo de Syberia: {name}')
        paths.add(name.casefold())
    for voice_id, entry in entries.items():
        name = entry['bank']
        start, size = entry['offset'], entry['size']
        audio_fields = (entry.get('frames'), entry.get('channels'), entry.get('sample_rate'))
        if (name not in banks or type(start) is not int or type(size) is not int
                or start < 0 or size <= 0 or start + size > banks[name]['size']
                or any(type(value) is not int or value <= 0 for value in audio_fields)
                or not valid_hash(entry.get('sha256'))):
            raise ValueError(f'Recurso inválido en el catálogo de Syberia: {voice_id}')
        slots[name].append((start, start + size))
    for name, ranges in slots.items():
        ranges.sort()
        if any(end > next_start for (_, end), (next_start, _) in zip(ranges, ranges[1:])):
            raise ValueError(f'Hay voces que comparten espacio en el banco {Path(name).name}.')
    return banks, entries


def approved_audio(data, entries):
    result = defaultdict(dict)
    database = confined(data, 'jobs.sqlite3')
    if not database.is_file():
        raise ValueError('Abre el doblaje de Syberia para preparar su cola de voces.')
    with closing(sqlite3.connect(database)) as db:
        rows = db.execute("SELECT id, output_wem, result_sha FROM jobs WHERE status='approved'").fetchall()
    for voice_id, raw_path, digest in rows:
        entry = entries.get(voice_id)
        if not entry or not raw_path or not valid_hash(digest):
            raise ValueError(f'La voz aprobada {voice_id} no tiene un archivo listo para Syberia.')
        path = data / raw_path
        if not path.is_relative_to(data):
            raise ValueError(f'La voz {voice_id} está fuera de la carpeta de doblaje.')
        blob = confined(data, path.relative_to(data)).read_bytes()
        expected = entry['frames'], entry['channels'], entry['sample_rate']
        if len(blob) != entry['size'] or hash_bytes(blob) != digest or wem_metadata(blob) != expected:
            raise ValueError(f'El WEM de {voice_id} no conserva la integridad o el formato del recurso.')
        result[entry['bank']][voice_id] = blob, digest
    return result
