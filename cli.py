"""DiscForge RU command-line companion (does not require PySide6)."""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
import threading

from core import CAPACITIES, DiscForgeError, create_bluray, probe_media
from player_profiles import PLAYER_PROFILES


def _chapter(value: str) -> float:
    try:
        parts = value.strip().split(':')
        if len(parts) != 3:
            raise ValueError()
        hours, mins = int(parts[0]), int(parts[1])
        secs = float(parts[2])
        if hours < 0 or mins < 0 or mins > 59 or not math.isfinite(secs) or secs < 0 or secs >= 60:
            raise ValueError()
        return 3600 * hours + 60 * mins + secs
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Требуется время вида ЧЧ:ММ:СС[.ммм]') from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='DiscForge RU — авторинг Full HD Blu-ray')
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('probe', help='Анализ файла')
    a.add_argument('file')
    a.add_argument('--ffprobe', default='ffprobe')
    b = sub.add_parser('build', help='Собрать ISO/BDMV; меню включается через --menu-title')
    b.add_argument('file')
    b.add_argument('--profile', choices=sorted(CAPACITIES), default='BD25')
    b.add_argument('--player', choices=sorted(PLAYER_PROFILES), default='universal',
                   help='Профиль проигрывателя (giec-g2805 экспериментальный)')
    b.add_argument('--output', default='DiscForge_Output')
    b.add_argument('--ffmpeg', default='ffmpeg')
    b.add_argument('--ffprobe', default='ffprobe')
    b.add_argument('--tsmuxer', default='tsMuxeR')
    b.add_argument('--folder', action='store_true', help='Создать BDMV вместо ISO')
    b.add_argument('--nvenc', action='store_true', help='Экспериментальный режим NVIDIA NVENC')
    b.add_argument('--cpu-filters', action='store_true', help='Отключить NVDEC/CUDA, оставить CPU-фильтры')
    b.add_argument('--processing', choices=['auto','copy','video_copy','encode'], default='auto',
                   help='Автовыбор, копирование всех потоков, копирование видео + AC-3 или перекодирование')
    b.add_argument('--audio-track', type=int, action='append', help='Глобальный index дорожки из probe; можно повторить')
    b.add_argument('--no-audio', action='store_true', help='Не включать звук')
    b.add_argument('--chapter', type=_chapter, action='append', help='Глава вида 00:10:00')
    b.add_argument('--menu-title', help='Добавить меню BD-J с этим названием (требует PySide6)')
    b.add_argument('--menu-theme', choices=['amber', 'sapphire', 'midnight', 'graphite', 'cinema'], default='amber')
    b.add_argument('--menu-language', choices=['ru', 'en'], default='ru')
    b.add_argument('--menu-background', help='Изображение фона меню')
    args = p.parse_args(argv)
    try:
        info = probe_media(args.file, args.ffprobe)
        if args.command == 'probe':
            print(json.dumps(dataclasses.asdict(info), ensure_ascii=False, indent=2))
        else:
            if args.no_audio and args.audio_track:
                raise DiscForgeError('Нельзя совместить --no-audio и --audio-track.')
            if args.no_audio or args.audio_track is not None:
                from audio_selection import select_tracks
                info = select_tracks(info, [] if args.no_audio else args.audio_track)
            chapters = None
            if args.chapter:
                chapters = sorted(set([0.0, *args.chapter]))
                if chapters[-1] >= info.duration:
                    raise DiscForgeError('Отметка главы должна быть меньше длительности фильма.')
            menu = None
            if args.menu_title is not None:
                os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
                try:
                    from PySide6.QtGui import QGuiApplication
                except ImportError as exc:
                    raise DiscForgeError('Для меню установите зависимости из requirements.txt.') from exc
                from disc_menu import MenuDesign, import_background
                app = QGuiApplication.instance() or QGuiApplication([])
                menu = MenuDesign(args.menu_title, args.menu_theme, args.menu_language,
                                  import_background(args.menu_background) if args.menu_background else '')
            print('Меню BD-J: проверьте воспроизведение перед записью.' if menu else 'Создаётся Blu-ray без меню.', file=sys.stderr)
            done = create_bluray(info, args.profile, args.output, args.ffmpeg, args.tsmuxer,
                                 not args.folder, args.nvenc, threading.Event(), print,
                                 lambda n: print(f'\r{n:.0f}% ', end='', flush=True), chapters, menu,
                                 processing_mode=args.processing, ffprobe=args.ffprobe, resilient=True, gpu_frames=not args.cpu_filters,
                                  player_profile=args.player)
            print('\nРезультат:', done)
        return 0
    except (DiscForgeError, OSError, ValueError, RuntimeError) as exc:
        print('ОШИБКА:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
