"""Rebuild Wwise 134 dialogue banks with verified replacement media lengths."""

from io import BytesIO
from struct import pack, pack_into, unpack_from

from wwise import chunks, event_id, objects


def read_layout(blob):
    layout = chunks(BytesIO(blob), len(blob))
    if tuple(layout) != (b'BKHD', b'DIDX', b'DATA', b'HIRC'):
        raise ValueError('El banco no tiene la disposición esperada de Wwise 134.')
    return layout


def rebuild(blob, edits, language):
    layout = read_layout(blob)
    header, _ = layout[b'BKHD']
    didx_at, didx_size = layout[b'DIDX']
    data_at, data_size = layout[b'DATA']
    hirc_at, hirc_size = layout[b'HIRC']
    if unpack_from('<I', blob, header)[0] != 134 or data_at % 16 or didx_size % 12:
        raise ValueError('Disposición de audio desconocida.')
    original = {}
    for index in range(didx_at, didx_at + didx_size, 12):
        media, offset, size = unpack_from('<III', blob, index)
        if media in original or offset % 16 or offset + size > data_size:
            raise ValueError('Índice de audio inválido.')
        original[media] = offset, size
    if not edits or not edits.keys() <= original.keys():
        raise ValueError('Faltan recursos de voz en el índice.')

    new_data = bytearray()
    new_offsets = {}
    for media, (offset, size) in sorted(original.items(), key=lambda pair: pair[1][0]):
        padding = (-len(new_data)) % 16
        new_data.extend(bytes(padding))
        audio = edits.get(media, blob[data_at + offset:data_at + offset + size])
        new_offsets[media] = len(new_data), len(audio)
        new_data.extend(audio)

    hirc = bytearray(blob[hirc_at:hirc_at + hirc_size])
    objects(hirc)
    patched = set()
    at = 4
    for _ in range(unpack_from('<I', hirc)[0]):
        kind, size, _ = unpack_from('<BII', hirc, at)
        payload = at + 9
        if kind == 2:
            _, stream, media, memory_size = unpack_from('<IBII', hirc, payload)
            if media in edits:
                if stream != 0 or memory_size != original[media][1]:
                    raise ValueError(f'La referencia HIRC al WEM {media} no coincide.')
                pack_into('<I', hirc, payload + 9, new_offsets[media][1])
                patched.add(media)
        at += 5 + size
    if patched != edits.keys():
        raise ValueError('Faltan referencias HIRC para los diálogos modificados.')

    prefix = bytearray(blob[:data_at])
    pack_into('<I', prefix, header + 8, event_id(language))
    for index in range(didx_at, didx_at + didx_size, 12):
        media, = unpack_from('<I', blob, index)
        pack_into('<II', prefix, index + 4, *new_offsets[media])
    pack_into('<I', prefix, data_at - 4, len(new_data))
    return bytes(prefix) + new_data + pack('<4sI', b'HIRC', len(hirc)) + hirc
