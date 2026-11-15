"""Read checked supplementary voices and bind them to the installed Wwise media."""

from collections import defaultdict
from hashlib import sha256
import json

from patch_inputs import wem_metadata
from syberia_scan import BANK_DIR, ENGLISH
from wwise import Bank, event_id


EVENTS = {
    249979296: ('DFr_67A1B49B', 'DFr_E9B9461F'),
    146210980: ('DFr_21DBD63B', 'DFr_3D5E0ED2'),
}
PIGEON_EFFECT = '225858950'
PIGEON_EVENTS = {'DFr_0C5FC599', 'DFr_A0ACE361', 'DFr_E117E9D0'}


def ambient_edits(game, work):
    banks, aliases = defaultdict(dict), defaultdict(dict)
    checked = set()
    originals = {}
    for path in sorted((work / 'render').glob('*.wem')):
        stem = path.stem
        script_path = work / f'{stem}.json'
        receipt_path = path.with_suffix('.json')
        if not script_path.is_file() or not receipt_path.is_file():
            continue
        script = script_path.read_bytes()
        row = json.loads(script)
        receipt = json.loads(receipt_path.read_bytes())
        wem = path.read_bytes()
        if (receipt['script'] != sha256(script).hexdigest() or receipt['sha256'] != sha256(wem).hexdigest()
                or [line.get('text') for line in receipt['lines']] != [line[3] for line in row['lines']]
                or any('failed' in line for line in receipt['lines'])):
            continue
        for folder, name, media, _ in row['refs']:
            if folder not in (ENGLISH, 'Windows') or name == 'stream':
                continue
            relative = BANK_DIR / ENGLISH / f'{name}.bnk' if folder == ENGLISH else BANK_DIR / f'{name}.bnk'
            if relative not in originals:
                originals[relative] = Bank(game / relative)
            source = originals[relative]
            original = source.read_embedded(media)
            if sha256(original).hexdigest() != row['sha'] or wem_metadata(original) != wem_metadata(wem):
                raise ValueError(f'El medio de origen no coincide: {name}/{media}.')
            if media in EVENTS:
                old, new = (event_id('DLG_' + fragment) for fragment in EVENTS[media])
                sound = source.direct_sound(old)
                if new in source.objects or sound is None or sound['media_id'] != media:
                    raise ValueError(f'El evento de origen no coincide: {name}/{media}.')
                aliases[relative.as_posix()][old] = new
            bank_edits = banks[relative.as_posix()]
            if media in bank_edits and bank_edits[media] != wem:
                raise ValueError(f'Hay dos reemplazos para el medio {name}/{media}.')
            bank_edits[media] = wem
            checked.add(stem)
    return banks, aliases, checked


def rename_events(blob, hirc, aliases):
    from struct import pack_into, unpack_from

    changes = set()
    start, size = hirc
    count, = unpack_from('<I', blob, start)
    pos = start + 4
    for _ in range(count):
        kind, length, identity = unpack_from('<BII', blob, pos)
        if kind == 4 and identity in aliases:
            pack_into('<I', blob, pos + 5, aliases[identity])
            changes.add(identity)
        pos += 5 + length
    if pos != start + size or changes != aliases.keys():
        raise ValueError('No se pudieron enlazar los eventos de voz.')
