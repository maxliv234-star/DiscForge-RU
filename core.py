"""DiscForge RU backend: media probing, BD budget and Blu-ray job pipeline.

This module has no GUI dependencies and is independently unit-testable.
"""
from __future__ import annotations

import json
import math
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from bdmv_preflight import inspect as inspect_bdmv
from tools.iso_udf_preflight import inspect as inspect_iso

SUPPORTED = {'.mkv', '.mp4', '.mov', '.m2ts', '.mts', '.ts', '.avi'}
CAPACITIES = {'BD25': 25_000_000_000, 'BD50': 50_000_000_000, 'BDXL100': 100_000_000_000}
HDR_TRANSFERS = {'smpte2084', 'arib-std-b67'}


class DiscForgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration: float
    size: int
    video_codec: str
    width: int
    height: int
    video_fps: str
    video_color_transfer: str
    audio_codec: str
    audio_channels: int
    audio_tracks: int
    subtitle_tracks: int

    @property
    def is_hdr(self) -> bool:
        return self.video_color_transfer in HDR_TRANSFERS

    @property
    def name(self) -> str:
        return Path(self.path).stem


def _run_probe(path: str, ffprobe: str = 'ffprobe') -> dict:
    cmd = [ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except FileNotFoundError as e:
        raise DiscForgeError('Не найден ffprobe. Укажите путь к ffprobe в настройках.') from e
    except subprocess.TimeoutExpired as e:
        raise DiscForgeError('ffprobe не ответил за 45 секунд.') from e
    if p.returncode != 0:
        raise DiscForgeError('Ошибка анализа файла: ' + p.stderr[-400:])
    try:
        return json.loads(p.stdout)
    except ValueError as e:
        raise DiscForgeError('ffprobe вернул некорректный JSON.') from e


def parse_probe(path: str, data: dict) -> MediaInfo:
    if not isinstance(data, dict) or not isinstance(data.get('streams'), list):
        raise DiscForgeError('ffprobe вернул некорректные данные о потоках.')
    streams = [s for s in data['streams'] if isinstance(s, dict)]
    videos = [s for s in streams if s.get('codec_type') == 'video' and not (
        s.get('disposition', {}).get('attached_pic') if isinstance(s.get('disposition'), dict) else False
    )]
    audios = [s for s in streams if s.get('codec_type') == 'audio']
    subs = [s for s in streams if s.get('codec_type') == 'subtitle']
    if not videos:
        raise DiscForgeError('В файле не обнаружен видеопоток.')
    v = videos[0]
    fmt = data.get('format') or {}
    if not isinstance(fmt, dict):
        raise DiscForgeError('ffprobe вернул некорректные данные о файле.')
    try:
        duration = float(fmt.get('duration') or v.get('duration') or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DiscForgeError('Не удалось определить длительность фильма.') from exc
    if not math.isfinite(duration) or duration <= 0:
        raise DiscForgeError('Не удалось определить длительность фильма.')
    a = audios[0] if audios else {}
    def nonnegative_int(value: object, label: str) -> int:
        try:
            result = int(value or 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DiscForgeError(f'ffprobe вернул некорректное значение: {label}.') from exc
        if result < 0:
            raise DiscForgeError(f'ffprobe вернул некорректное значение: {label}.')
        return result

    return MediaInfo(
        path=path, duration=duration,
        size=nonnegative_int(fmt.get('size') or (os.path.getsize(path) if os.path.isfile(path) else 0), 'размер'),
        video_codec=str(v.get('codec_name') or '?'),
        width=nonnegative_int(v.get('width'), 'ширина'), height=nonnegative_int(v.get('height'), 'высота'),
        video_fps=str(v.get('avg_frame_rate') or v.get('r_frame_rate') or '?'),
        video_color_transfer=str(v.get('color_transfer') or '').lower(),
        audio_codec=str(a.get('codec_name') or 'нет'),
        audio_channels=nonnegative_int(a.get('channels'), 'аудиоканалы'),
        audio_tracks=len(audios), subtitle_tracks=len(subs),
    )


def probe_media(path: str, ffprobe: str = 'ffprobe') -> MediaInfo:
    return parse_probe(path, _run_probe(path, ffprobe))


def bitrate_plan(duration: float, profile: str, has_audio: bool) -> int:
    if profile not in CAPACITIES:
        raise DiscForgeError('Неизвестный профиль диска: ' + profile)
    if not math.isfinite(duration) or duration <= 0:
        raise DiscForgeError('Некорректная длительность.')
    # Leave 7% spare room for transport stream mux overhead, filesystem, menus and rate fluctuations.
    room = CAPACITIES[profile] * 0.93
    audio_bps = 640_000 if has_audio else 0
    video_bps = int(room * 8 / duration - audio_bps)
    video_bps = min(video_bps, 28_000_000)  # keep within conservative BD encoding bounds
    if video_bps < 5_000_000:
        raise DiscForgeError('Фильм слишком длинный для выбранного диска при минимальном качестве 5 Мбит/с.')
    return video_bps


def make_video_command(ffmpeg: str, src: str, dst: str, bitrate: int, nvenc: bool) -> list[str]:
    # 1080p23.976 H.264/8-bit. 25/30/50/60 fps files have their frame rate converted.
    vf = ('fps=24000/1001,scale=1920:1080:force_original_aspect_ratio=decrease,'
          'pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1')
    cmd = [ffmpeg, '-hide_banner', '-nostdin', '-y', '-loglevel', 'error', '-progress', 'pipe:1',
           '-i', src, '-map', '0:v:0', '-an', '-sn', '-dn', '-vf', vf, '-pix_fmt', 'yuv420p',
           '-r', '24000/1001', '-c:v', 'h264_nvenc' if nvenc else 'libx264',
           '-profile:v', 'high', '-level:v', '4.1', '-b:v', str(bitrate),
           '-maxrate', '30000000', '-bufsize', '30000000', '-g', '24',
           '-bf', '3']
    if not nvenc:
        cmd += ['-preset', 'medium', '-x264-params', 'bluray-compat=1']
    else:
        cmd += ['-preset', 'p5']
    cmd += ['-f', 'h264', dst]
    return cmd


def make_audio_command(ffmpeg: str, src: str, dst: str, channels: int) -> list[str]:
    return [ffmpeg, '-hide_banner', '-nostdin', '-y', '-loglevel', 'error', '-progress', 'pipe:1',
            '-i', src, '-map', '0:a:0', '-vn', '-sn', '-dn', '-c:a', 'ac3', '-b:a', '640k',
            '-ar', '48000', '-ac', '6' if channels > 2 else '2', '-f', 'ac3', dst]


def write_meta(path: Path, video: Path, audio: Path | None,
               chapters: Sequence[float] | None = None) -> None:
    # Convert to slash separators; absolute paths are encoded as UTF-8 and quoted.
    def escaped(f: Path) -> str:
        return '"' + f.resolve().as_posix().replace('"', '') + '"'
    if chapters is None:
        opts = '--auto-chapters=10'
    else:
        if not chapters or abs(chapters[0]) > 0.001:
            raise DiscForgeError('Главы должны начинаться с отметки 00:00:00.')
        if any(t < 0 or not math.isfinite(t) for t in chapters):
            raise DiscForgeError('В списке глав есть недопустимая отметка.')
        if any(b <= a for a, b in zip(chapters, chapters[1:])):
            raise DiscForgeError('Отметки глав должны идти по возрастанию.')
        def fmt(sec: float) -> str:
            millis = round(sec * 1000)
            h, rest = divmod(millis, 3600000)
            m, rest = divmod(rest, 60000)
            s, ms = divmod(rest, 1000)
            return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'
        opts = '--custom-chapters=' + ';'.join(fmt(sec) for sec in chapters)
    content = 'MUXOPT --blu-ray ' + opts + '\n'
    content += f'V_MPEG4/ISO/AVC, {escaped(video)}, fps=23.976\n'
    if audio is not None:
        content += f'A_AC3, {escaped(audio)}, lang=und\n'
    path.write_text(content, encoding='utf-8')


def safe_name(value: str) -> str:
    result = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')
    return result[:90] or 'Movie'


def unique_target(root: Path, stem: str, iso: bool) -> Path:
    name = safe_name(stem)
    base = root / (name + '.iso' if iso else name)
    number = 2
    while base.exists():
        base = root / (f'{name}_{number}.iso' if iso else f'{name}_{number}')
        number += 1
    return base


def _require_binary(binary: str, label: str) -> None:
    if not binary:
        raise DiscForgeError('Не указан путь к ' + label)
    if Path(binary).is_file() or shutil.which(binary):
        return
    raise DiscForgeError(f'Не найден {label}: {binary}. Проверьте настройки.')


def run_command(cmd: list[str], stage: str, pct_start: int, pct_width: int,
                duration: float, cancel: threading.Event,
                log: Callable[[str], None], progress: Callable[[int], None]) -> None:
    log(f'{stage}...')
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace', bufsize=1, creationflags=creationflags)
    except OSError as e:
        raise DiscForgeError(f'Не удаётся запустить {Path(cmd[0]).name}: {e}') from e
    errors = []
    output: queue.SimpleQueue[str | None] = queue.SimpleQueue()
    def read_output() -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                output.put(line)
        finally:
            output.put(None)
    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        while True:
            if cancel.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise DiscForgeError('Операция отменена пользователем.')
            try:
                raw = output.get(timeout=0.1)
            except queue.Empty:
                continue
            if raw is None:
                break
            line = raw.strip()
            if line.startswith('out_time='):
                try:
                    h, m, s = line.partition('=')[2].split(':')
                    seconds = int(h)*3600 + int(m)*60 + float(s)
                    progress(pct_start + min(pct_width-1, int(seconds/duration*pct_width)))
                except (ValueError, ZeroDivisionError):
                    pass
            elif line and not re.match(r'^(frame|fps|bitrate|total_size|out_time_\w+|speed|progress|dup_frames|drop_frames)=', line):
                errors.append(line)
                if len(errors) > 25:
                    errors.pop(0)
        returncode = proc.wait()
        if cancel.is_set():
            raise DiscForgeError('Операция отменена пользователем.')
        if returncode != 0:
            raise DiscForgeError(f'{stage} завершён с ошибкой (код {returncode}): ' + '\n'.join(errors[-5:]))
        progress(pct_start + pct_width)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        reader.join(timeout=2)
        if proc.stdout is not None:
            proc.stdout.close()




def run_tsmuxer(tsmuxer: str, meta: Path, destination: Path, cancel: threading.Event,
                 log: Callable[[str], None]) -> None:
    """Run tsMuxer with cancellation and bounded stderr capture."""
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        proc = subprocess.Popen([tsmuxer, str(meta), str(destination)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace', creationflags=creationflags)
    except OSError as exc:
        raise DiscForgeError(f'Не удалось запустить tsMuxer: {exc}') from exc
    lines: list[str] = []
    def read_output() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.strip():
                lines.append(line.strip())
                if len(lines) > 40:
                    del lines[:10]
    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        while proc.poll() is None:
            if cancel.wait(0.25):
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise DiscForgeError('Операция отменена пользователем.')
        reader.join(timeout=2)
        if cancel.is_set():
            raise DiscForgeError('Операция отменена пользователем.')
        if proc.returncode:
            raise DiscForgeError('tsMuxer завершился с ошибкой: ' + '\n'.join(lines[-12:]))
        log('tsMuxer: структура создана.')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def create_bluray(info: MediaInfo, profile: str, output_root: str,
                   ffmpeg: str, tsmuxer: str, iso: bool, nvenc: bool,
                   cancel: threading.Event, log: Callable[[str], None],
                   progress: Callable[[int], None],
                   chapters: Sequence[float] | None = None) -> Path:
    """Encode to BD-oriented H.264 + AC3, then author BDMV directory or image.

    This is the first compatible-oriented implementation, NOT independently verified BD spec compliance.
    """
    if not Path(info.path).is_file():
        raise DiscForgeError('Исходный файл не найден.')
    if info.is_hdr:
        raise DiscForgeError('HDR10/HLG пока не обрабатывается. Для этого файла нужен будущий UHD-модуль.')
    _require_binary(ffmpeg, 'FFmpeg')
    _require_binary(tsmuxer, 'tsMuxeR')
    bitrate = bitrate_plan(info.duration, profile, info.audio_tracks > 0)
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    target = unique_target(root, info.name, iso)
    log(f'Профиль: {profile}, видео: {bitrate/1e6:.1f} Мбит/с, выход: {target}')
    log('ВНИМАНИЕ: эта альфа-версия создаёт Blu-ray БЕЗ интерактивного меню.')
    log('Предупреждение: кадры будут приведены к 23,976 fps; конвертация может повлиять на плавность.')
    with tempfile.TemporaryDirectory(prefix='DiscForge_work_', dir=root) as tmp:
        work = Path(tmp)
        video = work / 'video.h264'
        audio = work / 'audio.ac3' if info.audio_tracks else None
        meta = work / 'project.meta'
        run_command(make_video_command(ffmpeg, info.path, str(video), bitrate, nvenc),
                    'Кодирование видео', 0, 84 if audio else 92, info.duration, cancel, log, progress)
        if audio:
            run_command(make_audio_command(ffmpeg, info.path, str(audio), info.audio_channels),
                        'Кодирование аудио', 84, 8, info.duration, cancel, log, progress)
        write_meta(meta, video, audio, chapters)
        if cancel.is_set():
            raise DiscForgeError('Операция отменена пользователем.')
        # Author to an intermediate output first; move to destination only on success.
        author_target = work / ('disc.iso' if iso else 'disc')
        log('Формирование структуры Blu-ray через tsMuxer...')
        run_tsmuxer(tsmuxer, meta, author_target, cancel, log)
        if cancel.is_set():
            raise DiscForgeError('Операция отменена пользователем.')
        if not author_target.exists():
            raise DiscForgeError('tsMuxer не создал выходной файл/папку.')
        if iso:
            size = author_target.stat().st_size
        else:
            size = sum(f.stat().st_size for f in author_target.rglob('*') if f.is_file())
            if not (author_target / 'BDMV').is_dir():
                raise DiscForgeError('tsMuxer не создал каталог BDMV.')
        if size > CAPACITIES[profile]:
            raise DiscForgeError(f'Размер результата {size / 1e9:.2f} ГБ превышает {profile}. Файлы болванки не затронуты.')
        # Reject invalid Full HD outputs before moving them to the finished folder.
        # This ISO preflight inspects UDF metadata only; it does NOT prove a valid
        # directory tree, a playable BDMV, or working BD-J/HDMV menus.
        if not iso and profile in ('BD25', 'BD50'):
            report = inspect_bdmv(author_target, profile)
            if not report.structurally_valid:
                raise DiscForgeError('Проверка BDMV не пройдена: ' + '; '.join(report.errors[:8]))
            log('Структурная проверка BDMV пройдена; совместимость с плеером не подтверждена.')
        elif iso and profile in ('BD25', 'BD50'):
            report = inspect_iso(author_target, profile)
            if not report.valid:
                raise DiscForgeError('Проверка ISO UDF 2.50 не пройдена: ' + '; '.join(report.errors[:8]))
            log('ISO: метаданные UDF 2.50 проверены; BDMV внутри ISO и работа меню не проверены.')
        shutil.move(str(author_target), str(target))
        progress(100)
        log(f'Готово: {target} ({size/1e9:.2f} ГБ).')
        return target
