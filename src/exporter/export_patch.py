"""Export portable Syberia voice replacements from the local dubbing project."""

import argparse
from contextlib import closing
from hashlib import sha256
from collections import defaultdict
import json
from pathlib import Path
import sqlite3
from struct import pack_into, unpack_from
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from ambient_patch import PIGEON_EFFECT, PIGEON_EVENTS, ambient_edits, rename_events
from bank_rebuild import rebuild
from patch_inputs import approved_audio, file_sha, load_manifest, wem_metadata
from syberia_scan import BANK_DIR, ENGLISH
from wwise import Bank, chunks, event_id


ASSEMBLY = 'SyberiaTWB_Data/Managed/Assembly-CSharp.dll'
RECAP = 'SyberiaTWB_Data/StreamingAssets/videos/webm/previously.webm'
BASE_ASSEMBLY = 'ddbe711799a764ca30fd6af40ecd14c13c0735d8a5d76ae1026f7ca628505fa7'
SPANISH = 'Spanish(Spain)'


def playable_wem(blob):
    """End the RIFF at the audio data so the game's Vorbis decoder accepts it."""
    wem_metadata(blob)
    at = 12
    while at < len(blob):
        tag, size = unpack_from('<4sI', blob, at)
        at += 8 + size
        if tag == b'data':
            break
    if at == len(blob):
        return blob
    tail = blob[at:]
    if tail[:4] != b'JUNK':
        raise ValueError('Hay un bloque inesperado después de los datos del WEM.')
    result = bytearray(blob[:at])
    pack_into('<I', result, 4, at - 8)
    return bytes(result)


def export(data, game, modified_assembly, output, preview, longer_voices=None, extra=None, recap=None, ambience=None):
    import bsdiff4

    data, game = data.resolve(), game.resolve()
    banks, entries = load_manifest(data)
    with closing(sqlite3.connect(data / 'jobs.sqlite3')) as db:
        sounds = {voice for voice, in db.execute(
            "SELECT id FROM jobs WHERE kind='retained_nonverbal' AND status='retained'")}
        unreviewed = {voice for voice, in db.execute(
            "SELECT id FROM jobs WHERE status='approved' AND voice_approved!=1")}
    if unreviewed:
        raise ValueError(f'Hay {len(unreviewed)} voces pendientes de confirmar.')
    audio = approved_audio(data, entries)
    disputed = {}
    for audit in data.glob('auditoria_syberia-*.json'):
        for row in json.loads(audit.read_text(encoding='utf-8'))['held']:
            disputed.setdefault(row['id'], set()).add(row.get('sha256'))
    for voice, hashes in disputed.items():
        bank = audio.get(entries[voice]['bank'], {})
        if voice not in bank:
            continue
        report = json.loads((data / 'generated' / f'{voice}.json').read_text(encoding='utf-8'))
        if bank[voice][1] in hashes or not report.get('reviewed_text') or report.get('sha256') != bank[voice][1]:
            del bank[voice]
    selected = {voice for rows in audio.values() for voice in rows}
    longer = {}
    if longer_voices is not None:
        records = json.loads((longer_voices / 'one-liners.json').read_text(encoding='utf-8'))['voices']
        for voice, info in records.items():
            if voice in selected or voice in sounds:
                continue
            entry = entries[voice]
            wem = (longer_voices / f'{voice}.wem').read_bytes()
            if (info['bank'] != entry['bank'] or sha256(wem).hexdigest() != info['sha256']
                    or wem_metadata(wem) != (info['frames'], entry['channels'], entry['sample_rate'])):
                raise ValueError(f'El WEM de duración variable {voice} cambió.')
            longer.setdefault(info['bank'], {})[voice] = (wem, info)
            selected.add(voice)
    if not selected or selected & sounds or (not preview and selected | sounds != set(entries)):
        raise ValueError(f'Cobertura insuficiente para exportar: {len(selected)}/{len(entries) - len(sounds)}.')
    extra_embedded, extra_prefetch, extra_external = defaultdict(dict), defaultdict(list), {}
    extra_total = extra_selected = 0
    events_without_media = []
    if extra is not None:
        source_catalog = json.loads((extra / 'catalogo-adicional.json').read_text(encoding='utf-8'))
        catalog = source_catalog['targets']
        events_without_media = source_catalog['without_audio_target']
        accepted_path = extra / 'extra-verificado/manifest.json'
        accepted = json.loads(accepted_path.read_text(encoding='utf-8')) if accepted_path.exists() else {}
        groups = defaultdict(list)
        for key, info in catalog.items():
            groups[info['event']].append((key, info))
        extra_total = len(groups)
        for group in groups.values():
            if not all(key in accepted for key, _ in group):
                continue
            extra_selected += 1
            for key, info in group:
                wem = (extra / 'extra-verificado' / f'{key}.wem').read_bytes()
                if (sha256(wem).hexdigest() != accepted[key]['sha256'] or wem_metadata(wem) !=
                        (info['frames'], info['channels'], info['sample_rate'])):
                    raise ValueError(f'El WEM adicional {key} cambió.')
                wem = playable_wem(wem)
                media, bank, storage = info['media'], info['bank'], info['storage']
                if storage == 0:
                    extra_embedded[bank][media] = (key, wem)
                    continue
                name = f'{media}.wem'
                if name in extra_external and extra_external[name][1] != wem:
                    raise ValueError(f'El medio {name} tiene dos doblajes distintos.')
                extra_external[name] = key, wem
                if storage == 1:
                    size = info['prefetch']
                    if len(wem) < size:
                        raise ValueError(f'El WEM adicional {key} es menor que el prefijo original.')
                    extra_prefetch[bank].append((key, info['offset'], size, wem[:size]))
    if not preview and (extra is None or extra_selected != extra_total):
        raise ValueError(f'Faltan diálogos adicionales: {extra_selected}/{extra_total}.')
    assembly_path = game / ASSEMBLY
    original_assembly = assembly_path.read_bytes()
    if sha256(original_assembly).hexdigest() != BASE_ASSEMBLY:
        original_assembly = assembly_path.with_name('Assembly-CSharp.sin-doblaje.dll.bak').read_bytes()
    if sha256(original_assembly).hexdigest() != BASE_ASSEMBLY:
        raise ValueError('La DLL de origen no corresponde a la versión compatible.')
    target_assembly = modified_assembly.read_bytes()
    binary_patch = bsdiff4.diff(original_assembly, target_assembly)
    if bsdiff4.patch(original_assembly, binary_patch) != target_assembly:
        raise ValueError('La diferencia de la DLL no supera la verificación.')
    source_dir = game / BANK_DIR / ENGLISH
    ambient, aliases, ambient_ids = {}, {}, set()
    if ambience is not None:
        ambient, aliases, ambient_ids = ambient_edits(game, ambience)
        if not ambient_ids or recap is None:
            raise ValueError('Faltan el resumen o los audios ambientales verificados.')
        missing = {script.stem for script in ambience.glob('[0-9]*.json')} - ambient_ids
        if missing and not preview:
            raise ValueError(f'Faltan {len(missing)} pistas ambientales: {", ".join(sorted(missing))}.')
    inventory = []
    manifest = {
        'version': 4 if ambient_ids else 3 if recap is not None else 2, 'build': '8987614', 'preview': preview,
        'dialogues': len(selected), 'total_dialogues': len(entries) - len(sounds),
        'extra_dialogues': extra_selected, 'total_extra_dialogues': extra_total,
        'events_without_media': events_without_media,
        'retained_sounds': len(sounds - PIGEON_EVENTS) if PIGEON_EFFECT in ambient_ids else len(sounds), 'assembly': {
            'original': BASE_ASSEMBLY, 'patched': sha256(target_assembly).hexdigest(),
            'size': len(target_assembly),
        },
        'files': inventory,
    }
    if ambient_ids:
        manifest['ambient_tracks'] = len(ambient_ids)
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix='.syberia-', dir=output.parent, delete=False) as stream:
        staged = Path(stream.name)
    try:
        with ZipFile(staged, 'w', ZIP_DEFLATED, compresslevel=5) as archive:
            archive.writestr('selector.bsdiff', binary_patch)
            if recap is not None:
                original_video = (game / RECAP).read_bytes()
                dubbed_video = recap.read_bytes()
                delta = bsdiff4.diff(original_video, dubbed_video)
                if bsdiff4.patch(original_video, delta) != dubbed_video:
                    raise ValueError('La diferencia del vídeo no supera la verificación.')
                manifest['recap'] = {'original': sha256(original_video).hexdigest(),
                                     'patched': sha256(dubbed_video).hexdigest(), 'size': len(dubbed_video)}
                archive.writestr('recap.bsdiff', delta)
            shared = [game / name for name in ambient if (game / name).parent != source_dir]
            shared_names = {path.name for path in shared}
            if any(name in shared_names and name != 'Chap_7.bnk' for name in (p.name for p in source_dir.iterdir())):
                raise ValueError('Hay dos orígenes para un mismo banco de ambiente.')
            sources = [p for p in source_dir.iterdir() if p.name not in shared_names]
            if 'Chap_7.bnk' in shared_names and (source_dir / 'Chap_7.bnk').is_file():
                # The localized bank also provides the generic events and the stock localized media.
                localized = source_dir / 'Chap_7.bnk'
                relative = localized.relative_to(game).as_posix()
                generic = next(path for path in shared if path.name == localized.name)
                edits = ambient[generic.relative_to(game).as_posix()]
                if not edits.keys() <= ambient.get(relative, {}).keys():
                    raise ValueError('Falta la versión localizada de una voz de Chap_7.')
                shared.remove(generic)
                sources.append(localized)
            for path in sorted([*sources, *shared], key=lambda item: (item.name, str(item))):
                if path.suffix not in ('.bnk', '.wem'):
                    continue
                digest = file_sha(path)
                generic = path.parent != source_dir
                target_name = path.name
                record = {'name': target_name, 'original': digest, 'patched': digest, 'writes': []}
                if generic:
                    record['shared_source'] = path.name
                inventory.append(record)
                if path.suffix != '.bnk':
                    if path.name in extra_external:
                        key, wem = extra_external[path.name]
                        resource = f'extra/{key}.wem'
                        archive.writestr(resource, wem)
                        record.update(patched=sha256(wem).hexdigest(), resource=resource, resource_size=len(wem))
                    continue
                relative = path.relative_to(game).as_posix()
                if relative in banks and digest != banks[relative]['sha256']:
                    raise ValueError(f'El banco de origen ha cambiado: {path.name}')
                blob = bytearray(path.read_bytes())
                with path.open('rb') as stream:
                    offset, length = chunks(stream, len(blob))[b'BKHD']
                language_at = offset + 8
                language = 'SFX' if generic else ENGLISH
                if length < 12 or blob[language_at:language_at + 4] != event_id(language).to_bytes(4, 'little'):
                    raise ValueError(f'El banco no está marcado como inglés: {path.name}')
                blob[language_at:language_at + 4] = event_id(SPANISH).to_bytes(4, 'little')
                record['language_at'] = language_at
                targets = audio.get(relative, {})
                for key, begin, size, prefix in extra_prefetch.get(relative, []):
                    if len(prefix) != size or begin < 20 or begin + size > len(blob):
                        raise ValueError(f'La cabecera de audio adicional {key} no coincide.')
                    blob[begin:begin + size] = prefix
                    resource = f'extra/{key}.prefetch'
                    archive.writestr(resource, prefix)
                    record['writes'].append({
                        'offset': begin, 'size': size, 'sha256': sha256(prefix).hexdigest(), 'resource': resource,
                    })
                record['writes'].sort(key=lambda edit: edit['offset'])
                extended = longer.get(relative, {})
                other = extra_embedded.get(relative, {})
                new_ambient = ambient.get(relative, {})
                event_aliases = aliases.get(relative, {})
                if targets or extended or other or new_ambient:
                    bank_index = Bank(path)
                    replacements = {}
                    record['replacements'] = []
                    media_by_slot = {slot: media for media, slot in bank_index.media.items()}
                    for voice, (wem, _) in sorted(targets.items()):
                        entry = entries[voice]
                        begin, size = entry['offset'], entry['size']
                        media = media_by_slot.get((begin, size))
                        if media is None or media in replacements or sha256(blob[begin:begin + size]).hexdigest() != entry['sha256']:
                            raise ValueError(f'El índice original de {voice} no coincide.')
                        wem = playable_wem(wem)
                        replacements[media] = wem
                        resource = f'audio/{voice}.wem'
                        archive.writestr(resource, wem)
                        record['replacements'].append({'media': media, 'size': len(wem),
                                                       'sha256': sha256(wem).hexdigest(), 'resource': resource})
                    for voice, (wem, info) in sorted(extended.items()):
                        entry = entries[voice]
                        media = info['media_id']
                        if media in replacements or bank_index.media.get(media) != (entry['offset'], entry['size']):
                            raise ValueError(f'La referencia al medio {voice} no coincide.')
                        wem = playable_wem(wem)
                        replacements[media] = wem
                        resource = f'audio/{voice}.wem'
                        archive.writestr(resource, wem)
                        record['replacements'].append({
                            'media': media, 'size': len(wem), 'sha256': sha256(wem).hexdigest(), 'resource': resource,
                        })
                    for media, (key, wem) in other.items():
                        if media in replacements or media not in bank_index.media:
                            raise ValueError(f'El medio {media} ya tiene un doblaje o no está en el banco.')
                        replacements[media] = wem
                        resource = f'extra/{key}.wem'
                        archive.writestr(resource, wem)
                        record['replacements'].append({
                            'media': media, 'size': len(wem), 'sha256': sha256(wem).hexdigest(), 'resource': resource,
                        })
                    for media, wem in new_ambient.items():
                        if media in replacements or media not in bank_index.media:
                            raise ValueError(f'El medio ambiental {media} ya tiene un reemplazo.')
                        wem = playable_wem(wem)
                        replacements[media] = wem
                        resource = f'ambiente/{target_name}/{media}.wem'
                        archive.writestr(resource, wem)
                        record['replacements'].append({'media': media, 'size': len(wem),
                                                       'sha256': sha256(wem).hexdigest(), 'resource': resource})
                    blob = rebuild(blob, replacements, SPANISH)
                if event_aliases:
                    from bank_rebuild import read_layout
                    blob = bytearray(blob)
                    rename_events(blob, read_layout(blob)[b'HIRC'], event_aliases)
                    record['event_aliases'] = event_aliases
                record['patched'] = sha256(blob).hexdigest()
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
        if not {Path(name).name for name in banks} <= {
                record['name'] for record in inventory if 'language_at' in record}:
            raise ValueError('Faltan bancos originales para construir el paquete.')
        staged.replace(output)
    finally:
        staged.unlink(missing_ok=True)
    print(f'{len(selected)} diálogos, {extra_selected}/{extra_total} adicionales, '
          f'{manifest["retained_sounds"]} sonidos originales y {len(inventory)} archivos comprobados.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('game', type=Path)
    parser.add_argument('selector', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--preview', action='store_true', help='Genera un paquete de prueba con voces pendientes.')
    parser.add_argument('--longer-voices', type=Path)
    parser.add_argument('--extra', type=Path)
    parser.add_argument('--recap', type=Path)
    parser.add_argument('--ambience', type=Path)
    args = parser.parse_args()
    export(args.data, args.game, args.selector, args.output, args.preview, args.longer_voices, args.extra, args.recap,
           args.ambience)
