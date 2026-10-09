"""DiscForge RU command-line companion (does not require PySide6)."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import threading

from core import CAPACITIES, DiscForgeError, create_bluray, probe_media


def _chapter(value: str) -> float:
    try:
        parts = value.strip().split(':')
        if len(parts) != 3:
            raise ValueError()
        hours, mins = int(parts[0]), int(parts[1])
        secs = float(parts[2])
        if hours < 0 or mins < 0 or mins > 59 or secs < 0 or secs >= 60:
            raise ValueError()
        return 3600 * hours + 60 * mins + secs
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Требуется время вида ЧЧ:ММ:СС[.ммм]') from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='DiscForge RU alpha — Blu-ray без интерактивного меню')
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('probe', help='Анализ файла')
    a.add_argument('file')
    a.add_argument('--ffprobe', default='ffprobe')
    b = sub.add_parser('build', help='Собрать тестовый ISO/BDMV без меню')
    b.add_argument('file')
    b.add_argument('--profile', choices=sorted(CAPACITIES), default='BD25')
    b.add_argument('--output', default='DiscForge_Output')
    b.add_argument('--ffmpeg', default='ffmpeg')
    b.add_argument('--ffprobe', default='ffprobe')
    b.add_argument('--tsmuxer', default='tsMuxeR')
    b.add_argument('--folder', action='store_true', help='Создать BDMV вместо ISO')
    b.add_argument('--nvenc', action='store_true', help='Экспериментальный режим NVIDIA NVENC')
    b.add_argument('--chapter', type=_chapter, action='append', help='Глава вида 00:10:00')
    args = p.parse_args(argv)
    try:
        info = probe_media(args.file, args.ffprobe)
        if args.command == 'probe':
            print(json.dumps(dataclasses.asdict(info), ensure_ascii=False, indent=2))
        else:
            chapters = None
            if args.chapter:
                chapters = sorted(set([0.0, *args.chapter]))
                if chapters[-1] >= info.duration:
                    raise DiscForgeError('Отметка главы должна быть меньше длительности фильма.')
            print('ВНИМАНИЕ: версия alpha создаёт Blu-ray БЕЗ интерактивного меню.', file=sys.stderr)
            done = create_bluray(info, args.profile, args.output, args.ffmpeg, args.tsmuxer,
                                 not args.folder, args.nvenc, threading.Event(), print,
                                 lambda n: print(f'\r{n}% ', end='', flush=True), chapters)
            print('\nРезультат:', done)
        return 0
    except (DiscForgeError, OSError) as exc:
        print('ОШИБКА:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
