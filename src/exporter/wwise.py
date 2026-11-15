"""Read Wwise 134 dialogue events and their direct media references."""

from struct import iter_unpack, unpack, unpack_from


def event_id(name):
    # The same hash is published beside the event name in SoundbanksInfo.
    value = 2166136261
    for byte in name.lower().encode('ascii'):
        value = (value * 16777619 & 0xffffffff) ^ byte
    return value


def chunks(stream, size):
    result = {}
    offset = 0
    while offset < size:
        stream.seek(offset)
        header = stream.read(8)
        if len(header) != 8:
            raise ValueError('Cabecera de banco truncada.')
        tag, length = unpack('<4sI', header)
        offset += 8
        if tag in result or tag == bytes(4) or offset + length > size:
            raise ValueError('Índice de bloques de Wwise inválido.')
        result[tag] = offset, length
        offset += length
    return result


def read_block(stream, blocks, tag):
    offset, size = blocks.get(tag, (0, 0))
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError('Bloque de Wwise truncado.')
    return data


def action_ids(payload):
    count = 0
    for index, byte in enumerate(payload[:5], start=1):
        count = (count << 7) | (byte & 0x7f)
        if not byte & 0x80:
            if len(payload) != index + 4 * count:
                break
            return tuple(value for (value,) in iter_unpack('<I', payload[index:]))
    raise ValueError('Lista de acciones de Wwise inválida.')


def objects(data):
    count, = unpack_from('<I', data)
    offset = 4
    result = {}
    for _ in range(count):
        kind, size, object_id = unpack_from('<BII', data, offset)
        end = offset + 5 + size
        if size < 4 or end > len(data) or object_id in result:
            raise ValueError('Objeto HIRC inválido.')
        result[object_id] = kind, data[offset + 9:end]
        offset = end
    if offset != len(data):
        raise ValueError('El tamaño de HIRC no coincide con su índice.')
    return result


class Bank:
    def __init__(self, path):
        self.path = path
        with path.open('rb') as stream:
            blocks = chunks(stream, path.stat().st_size)
            if read_block(stream, blocks, b'BKHD')[:4] != b'\x86\0\0\0':
                raise ValueError('El banco no usa Wwise 134.')
            self.objects = objects(read_block(stream, blocks, b'HIRC'))
            data_offset, data_size = blocks.get(b'DATA', (0, 0))
            self.media = {}
            for media_id, offset, size in iter_unpack('<III', read_block(stream, blocks, b'DIDX')):
                if offset + size > data_size or media_id in self.media:
                    raise ValueError('Índice de audio DIDX inválido.')
                self.media[media_id] = data_offset + offset, size

    def direct_sound(self, event):
        kind, payload = self.objects.get(event, (None, b''))
        if kind != 4:
            return None
        actions = action_ids(payload)
        if len(actions) != 1:
            return None
        kind, payload = self.objects.get(actions[0], (None, b''))
        if kind != 3:
            return None
        action, sound = unpack_from('<HI', payload)
        if action != 0x0403:
            return None
        kind, payload = self.objects.get(sound, (None, b''))
        if kind != 2:
            return None
        plugin, stream_type, media, size = unpack_from('<IBII', payload)
        return {'sound_id': sound, 'plugin': plugin, 'stream_type': stream_type,
                'media_id': media, 'in_memory_size': size}

    def read_embedded(self, media):
        offset, size = self.media[media]
        with self.path.open('rb') as stream:
            stream.seek(offset)
            data = stream.read(size)
        if len(data) != size or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
            raise ValueError('WEM empotrado incompleto o inválido.')
        riff_size, = unpack_from('<I', data, 4)
        if riff_size + 8 > size:
            raise ValueError('WEM empotrado truncado.')
        return data[:riff_size + 8]
