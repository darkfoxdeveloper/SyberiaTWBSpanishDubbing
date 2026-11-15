"""Read-only inventory of the Steam edition of Syberia: The World Before."""

import argparse
import json
from pathlib import Path


APP_ID = '1410640'
DATA_DIR = Path('SyberiaTWB_Data')
BANK_DIR = DATA_DIR / 'StreamingAssets/Audio/GeneratedSoundBanks/Windows'
ENGLISH = 'English(US)'


def identify(game):
    game = Path(game)
    return (game / 'SyberiaTWB.exe').is_file() and (game / DATA_DIR).is_dir()


def read_prefix(path, size):
    try:
        with path.open('rb') as stream:
            return stream.read(size)
    except OSError:
        return b''


def scan(game):
    game = Path(game).resolve()
    banks = game / BANK_DIR
    metadata_path = banks / 'SoundbanksInfo.json'
    files = sorted(banks.rglob('*.bnk')) if banks.is_dir() else []
    verified = [path for path in files if read_prefix(path, 4) == b'BKHD']
    dialogue = set((banks / ENGLISH).glob('*_Dialog.bnk'))
    verified_dialogue = [path for path in verified if path in dialogue]
    try:
        manifest = json.loads(metadata_path.read_bytes())['SoundBanksInfo']['SoundBanks']
        if not isinstance(manifest, list) or not manifest:
            raise ValueError('No hay bancos en el índice.')
    except (OSError, ValueError, TypeError, KeyError):
        manifest = None

    installed = identify(game)
    if not installed:
        status = 'not_installed'
    elif not manifest or not verified_dialogue:
        status = 'incomplete'
    else:
        status = 'audio_available'

    return {
        'steam_app_id': APP_ID,
        'game': str(game),
        'status': status,
        'wwise_directory': str(banks),
        'wwise_metadata_readable': manifest is not None,
        'wwise_metadata_banks': len(manifest or []),
        'wwise_banks_with_header': len(verified),
        'english_dialogue_banks': [p.relative_to(game).as_posix() for p in verified_dialogue],
        'english_dialogue_bank_files': len(dialogue),
        'voice_language_folders': sorted({p.parent.name for p in verified if p.parent != banks}),
    }


def main():
    parser = argparse.ArgumentParser(description='Inventario de solo lectura de Syberia: The World Before')
    parser.add_argument('game', type=Path, help='Carpeta que contiene SyberiaTWB.exe')
    args = parser.parse_args()
    print(json.dumps(scan(args.game), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
