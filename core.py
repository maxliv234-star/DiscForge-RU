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
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Sequence

from bdmv_preflight import inspect as inspect_bdmv
from tools.iso_udf_preflight import inspect as inspect_iso
from disc_menu import MenuDesign, install_menu
from windows_iso import create_iso, pending_image
from audio_selection import selected_tracks, select_tracks, audio_outputs, stream_map, language
from player_profiles import PLAYER_PROFILES, G2805_COMBINED_PEAK_TARGET, encode_targets

SUPPORTED = {'.mkv', '.mp4', '.mov', '.m2ts', '.mts', '.ts', '.avi'}
CAPACITIES = {'BD25': 25_000_000_000, 'BD50': 50_000_000_000}
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
    video_details: dict = field(default_factory=dict)
    audio_details: dict = field(default_factory=dict)
    copy_report: object = None
    audio_streams: tuple = ()
    selected_audio: tuple | None = None
    subtitle_streams: tuple = ()
    selected_subtitles: tuple = ()
    source_chapters: tuple = ()
    chapter_notices: tuple = ()
    source_chapter_titles: tuple = ()
    audio_modes: dict = field(default_factory=dict)
    video_analysis: dict = field(default_factory=dict)

    @property
    def is_hdr(self) -> bool:
        return self.video_color_transfer in HDR_TRANSFERS

    @property
    def name(self) -> str:
        return Path(self.path).stem


def _run_probe(path: str, ffprobe: str = 'ffprobe') -> dict:
    cmd = [ffprobe, '-v', 'error', '-show_format', '-show_streams', '-show_chapters', '-of', 'json', path]
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

    from source_chapters import import_chapter_metadata
    source_chapters, source_chapter_titles, chapter_notices = import_chapter_metadata(data.get('chapters'), duration)
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
        video_details=dict(v), audio_details=dict(a),
        audio_streams=tuple(dict(s) for s in audios),
        subtitle_streams=tuple(dict(s) for s in subs),
        source_chapters=source_chapters, chapter_notices=chapter_notices,
        source_chapter_titles=source_chapter_titles,
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
    audio_bps = 640_000 * int(has_audio)
    video_bps = int(room * 8 / duration - audio_bps)
    video_bps = min(video_bps, 28_000_000, 44_000_000-audio_bps)  # keep within conservative BD encoding bounds
    if video_bps < 5_000_000:
        raise DiscForgeError('Фильм слишком длинный для выбранного диска при минимальном качестве 5 Мбит/с.')
    return video_bps


def make_video_command(ffmpeg: str, src: str, dst: str, bitrate: int, nvenc: bool, fast: bool = False) -> list[str]:
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
        cmd += ['-preset', 'fast' if fast else 'medium', '-x264-params', 'bluray-compat=1']
    else:
        cmd += ['-preset', 'p3' if fast else 'p5', '-bluray-compat', '1']
    cmd += ['-f', 'h264', dst]
    return cmd


def make_audio_command(ffmpeg: str, src: str, dst: str, channels: int) -> list[str]:
    return [ffmpeg, '-hide_banner', '-nostdin', '-y', '-loglevel', 'error', '-progress', 'pipe:1',
            '-i', src, '-map', '0:a:0', '-vn', '-sn', '-dn', '-c:a', 'ac3', '-b:a', '640k',
            '-ar', '48000', '-ac', '6' if channels > 2 else '2', '-f', 'ac3', dst]


def make_encode_command(ffmpeg, info, video, audio, bitrate, nvenc, fast=False):
    cmd = make_video_command(ffmpeg, info.path, str(video), bitrate, nvenc, fast)
    tracks = audio_outputs(info, audio)
    cmd[cmd.index('-maxrate')+1] = str(min(30_000_000, 44_000_000-640_000*len(tracks)))
    for target, stream in tracks:
        # Both elementary streams from one demux pass; no second read of the movie.
        cmd += ['-map', stream_map(stream), '-vn', '-sn', '-dn', '-c:a', 'ac3', '-b:a', '640k',
                '-ar', '48000', '-ac', '6' if int(stream.get('channels', info.audio_channels)) > 2 else '2',
                '-af', 'aresample=async=1:first_pts=0', '-f', 'ac3', str(target)]
    return cmd


def prepare_processing(info, mode, profile, ffprobe, ffmpeg, cancel, log):
    from smart_copy import analyze_copy, choose_mode, signature, MODES
    if mode not in MODES:
        raise DiscForgeError('Неизвестный режим обработки.')
    report = info.copy_report
    if report is not None and report.signature != signature(info.path, cancel):
        raise DiscForgeError('Исходник изменился после анализа. Удалите его из очереди и добавьте заново.')
    if mode == 'encode':
        return info, 'encode', 'Выбрано перекодирование видео; звук — по настройкам дорожек.'
    if report is None:
        log('Проверяем возможность копирования потоков без перекодирования…')
        info = replace(probe_media(info.path, ffprobe), selected_audio=info.selected_audio,
                       selected_subtitles=info.selected_subtitles, audio_modes=info.audio_modes)
        report = analyze_copy(info, ffprobe, ffmpeg, cancel)
        info = replace(info, copy_report=report)
    selected, reason = choose_mode(mode, report, info, CAPACITIES[profile])
    return info, selected, reason


def signature_changed(info, cancel=None):
    from smart_copy import signature
    return info.copy_report.signature != signature(info.path, cancel)


def make_copy_command(ffmpeg, info, video, audio, convert_audio=False):
    cmd = [ffmpeg, '-hide_banner', '-nostdin', '-y', '-loglevel', 'error', '-progress', 'pipe:1',
           '-i', info.path, '-map', f"0:{info.video_details['index']}", '-an', '-sn', '-dn',
           '-c:v', 'copy', '-bsf:v', 'h264_mp4toannexb', '-f', 'h264', str(video)]
    for target, stream in audio_outputs(info, audio):
        cmd += ['-map', stream_map(stream), '-vn', '-sn', '-dn']
        checked = getattr(info.copy_report, 'audio_results', {}).get(stream.get('index'), {})
        if convert_audio and not checked.get('ok', False):
            cmd += ['-c:a', 'ac3', '-b:a', '640k', '-ar', '48000', '-ac', '6' if int(stream.get('channels', info.audio_channels))>2 else '2',
                    '-af', 'aresample=async=1:first_pts=0']
        else:
            cmd += ['-c:a', 'copy']
        cmd += ['-f', stream.get('output_format', 'ac3'), str(target)]
    return cmd


def nvenc_available(ffmpeg, cancel, log):
    """Test the actual driver/encoder, not just the list of compiled codecs."""
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
               'color=size=1920x1080:rate=24000/1001', '-frames:v', '2',
               '-c:v', 'h264_nvenc', '-preset', 'p3', '-bluray-compat', '1', '-f', 'null', '-']
    # Use a separate cancellation token so a failed probe never cancels the build.
    probe_cancel = threading.Event()
    def stop_probe():
        probe_cancel.set()
    timer = threading.Timer(15, stop_probe)
    timer.start()
    try:
        if cancel.is_set():
            raise DiscForgeError('Операция отменена пользователем.')
        class Cancellation:
            def is_set(self): return cancel.is_set() or probe_cancel.is_set()
            def wait(self, seconds):
                cancel.wait(seconds)
                return self.is_set()
        run_command(command, 'Проверка NVIDIA NVENC', 0, 1, 1, Cancellation(), log, lambda _: None)
        return True
    except DiscForgeError as exc:
        if cancel.is_set():
            raise
        log('NVENC недоступен; выбран CPU x264. ' + str(exc))
        return False
    finally:
        timer.cancel()


def validate_chapters(chapters: Sequence[float], duration: float | None = None) -> None:
    if not chapters:
        raise DiscForgeError('Главы должны начинаться с отметки 00:00:00.')
    try:
        valid = all(not isinstance(t, bool) and isinstance(t, (int, float)) and
                    math.isfinite(t) and t >= 0 for t in chapters)
    except OverflowError:
        valid = False
    if not valid:
        raise DiscForgeError('В списке глав есть недопустимая отметка.')
    if chapters[0] != 0:
        raise DiscForgeError('Главы должны начинаться с отметки 00:00:00.')
    if any(b <= a for a, b in zip(chapters, chapters[1:])):
        raise DiscForgeError('Отметки глав должны идти по возрастанию.')
    if duration is not None and chapters[-1] >= duration:
        raise DiscForgeError('Отметка главы должна быть меньше длительности фильма.')


def write_meta(path: Path, video: Path, audio: Path | None,
               chapters: Sequence[float] | None = None, fps: str = '23.976', *, subtitles=(), width=1920, height=1080) -> None:
    # Convert to slash separators; absolute paths are encoded as UTF-8 and quoted.
    def escaped(f: Path) -> str:
        return '"' + f.resolve().as_posix().replace('"', '') + '"'
    if chapters is None:
        opts = '--auto-chapters=10'
    else:
        validate_chapters(chapters)
        def fmt(sec: float) -> str:
            millis = round(sec * 1000)
            h, rest = divmod(millis, 3600000)
            m, rest = divmod(rest, 60000)
            s, ms = divmod(rest, 1000)
            return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'
        opts = '--custom-chapters=' + ';'.join(fmt(sec) for sec in chapters)
    # TrueHD and its AC-3 companion share a PID. PES extension IDs distinguish
    # the two substreams; the bundled tsMuxer does not enable them implicitly.
    tracks = audio if isinstance(audio, list) else [(audio,{})] if audio is not None else []
    if os.name == 'nt':
        # Avoid the bundled muxer's unbuffered asynchronous Windows writer:
        # a full-length job returned success with a truncated final M2TS block.
        opts += ' --no-asyncio'
    if any(s.get('output_codec') == 'truehd' for _, s in tracks):
        opts += ' --new-audio-pes'
    content = 'MUXOPT --blu-ray ' + opts + '\n'
    content += f'V_MPEG4/ISO/AVC, {escaped(video)}, fps={fps}\n'
    for target, stream in tracks:
        content += f'{stream.get("output_mux", "A_AC3")}, {escaped(target)}, lang={language(stream)}\n'
    from subtitles import meta_lines
    content += meta_lines(subtitles, fps, width, height)
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
    if cancel.is_set():
        raise DiscForgeError('Операция отменена пользователем.')
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
                    progress(pct_start + max(0, min(pct_width-0.01, seconds/duration*pct_width)))
                except (ValueError, ZeroDivisionError):
                    pass
            elif line and not re.match(r'^(frame|fps|bitrate|total_size|out_time_\w+|speed|progress|dup_frames|drop_frames)=', line):
                errors.append(line)
                if len(errors) > 25:
                    errors.pop(0)
        while proc.poll() is None:
            if cancel.wait(0.1):
                raise DiscForgeError('Операция отменена пользователем.')
        returncode = proc.returncode
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
                 log: Callable[[str], None], progress=None) -> None:
    """Run tsMuxer with cancellation and bounded stderr capture."""
    if cancel.is_set():
        raise DiscForgeError('Операция отменена пользователем.')
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
            if progress:
                match = re.search(r'(\d+(?:\.\d+)?)%', line)
                if match:
                    progress(min(0.999, float(match.group(1))/100))
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
        if progress:
            progress(1.0)
        log('tsMuxer: структура создана.')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        reader.join(timeout=2)
        if proc.stdout is not None:
            proc.stdout.close()


def create_bluray(info: MediaInfo, profile: str, output_root: str,
                   ffmpeg: str, tsmuxer: str, iso: bool, nvenc: bool,
                   cancel: threading.Event, log: Callable[[str], None],
                   progress: Callable[[int], None],
                   chapters: Sequence[float] | None = None,
                   menu: MenuDesign | None = None, *, fast: bool = False, observer=None, processing_mode='encode', ffprobe='ffprobe',
                   resilient=False, gpu_frames=True, verification=None, video_bitrate=None, keep_authored=False, player_profile='universal') -> Path:
    """Encode to BD-oriented H.264 + AC3, then author BDMV directory or image.

    This is the first compatible-oriented implementation, NOT independently verified BD spec compliance.
    """
    if player_profile not in PLAYER_PROFILES:
        raise DiscForgeError('Неизвестный профиль проигрывателя.')
    if not Path(info.path).is_file():
        raise DiscForgeError('Исходный файл не найден.')
    if info.selected_audio is not None:
        try:
            info = select_tracks(info, info.selected_audio)
        except ValueError as exc:
            raise DiscForgeError(str(exc)) from exc
    from subtitles import select_subtitles, prepare_subtitles, menu_subtitles
    info = select_subtitles(info, info.selected_subtitles)
    # TrueHD always requires the verified pipeline, including legacy API callers.
    resilient = resilient or any(t.get('codec_name') == 'truehd' for t in selected_tracks(info))
    if menu is not None:
        if not isinstance(menu, MenuDesign):
            raise DiscForgeError('Некорректное меню проекта.')
        from disc_audio import menu_tracks
        menu = replace(menu, audio_tracks=menu_tracks(info), subtitle_tracks=menu_subtitles(info))
    info, selected_mode, recommendation = prepare_processing(info, processing_mode, profile, ffprobe, ffmpeg, cancel, log)
    log(recommendation)
    copying = selected_mode != 'encode'
    if info.is_hdr:
        raise DiscForgeError('HDR10/HLG пока не обрабатывается. Для этого файла нужен будущий UHD-модуль.')
    if cancel.is_set():
        raise DiscForgeError('Операция отменена пользователем.')
    if chapters is None and info.source_chapters:
        chapters = list(info.source_chapters)
    if chapters is not None:
        validate_chapters(chapters, info.duration)
    if menu is not None:
        if not isinstance(menu, MenuDesign):
            raise DiscForgeError('Некорректное меню проекта.')
        if menu.background:
            from disc_menu import background_image
            background_image(menu.background)
        if iso and os.name != 'nt':
            raise DiscForgeError('ISO с меню пока доступен на Windows. Выберите папку BDMV.')
        chapters = list(chapters) if chapters is not None else [0.0] + list(range(600, int(info.duration), 600))
        if len(chapters) > 999:
            raise DiscForgeError('Меню поддерживает не более 999 глав.')
        if not menu.chapter_titles:
            from source_chapters import titles_for_chapters
            menu = replace(menu, chapter_titles=titles_for_chapters(info, chapters))
        from disc_menu import validate_menu_navigation
        validate_menu_navigation(list(chapters), menu)
    _require_binary(ffmpeg, 'FFmpeg')
    _require_binary(tsmuxer, 'tsMuxeR')
    tracks = selected_tracks(info)
    if len(tracks) > 32:
        raise DiscForgeError('Blu-ray поддерживает не более 32 выбранных аудиодорожек.')
    bitrate = int(info.copy_report.video_bytes*8/info.duration) if copying else video_bitrate if video_bitrate is not None else bitrate_plan(info.duration, profile, len(tracks))
    if video_bitrate is not None and not copying:
        if type(video_bitrate) is not int or not 5_000_000 <= video_bitrate <= 28_000_000:
            raise DiscForgeError('Битрейт видео должен быть от 5 до 28 Мбит/с.')
        bitrate = video_bitrate
    if keep_authored and (iso or not resilient):
        raise DiscForgeError('Внутренняя сборка коллекции требует папку BDMV и кэш.')
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    estimated_stream = info.duration * (bitrate + 640_000 * len(tracks)) / 8 * 1.08
    required = int(estimated_stream * (3 if iso and (menu is not None or resilient) else 2)) + 256_000_000
    from build_cache import key as cache_key
    resume_dir = root / '.diskforge-cache' / cache_key(str(Path(info.path).resolve()).casefold())[:24]
    if resilient and (resume_dir / 'video.h264').is_file() and (resume_dir / 'disc/BDMV').is_dir():
        # Cache may already contain the large elementary streams and authored disc.
        # Reserve room for the new output; tool errors still leave checkpoints intact.
        required = int(estimated_stream) + 256_000_000
    if shutil.disk_usage(root).free < required:
        raise DiscForgeError(f'Недостаточно места для сборки. Освободите примерно {required/1e9:.1f} ГБ в выходной папке.')
    target = unique_target(root, info.name, iso)
    log(f'Профиль: {profile}, видео: {bitrate/1e6:.1f} Мбит/с, выход: {target}')
    log('Меню BD-J: перед записью проверьте воспроизведение на вашем плеере.' if menu else 'Диск без интерактивного меню.')
    if player_profile != 'universal':
        log('Проигрыватель: GIEC BDP-G2805 (экспериментальный профиль, не проверен физически).')
    if not copying:
        log('Предупреждение: кадры будут приведены к 23,976 fps; конвертация может повлиять на плавность.')
    else:
        log('Видео копируется без изменения изображения и частоты кадров. ' + ('Решение по каждой аудиодорожке будет показано отдельно.' if resilient else 'Совместимый звук копируется, остальные выбранные дорожки преобразуются в AC-3.'))
    from build_cache import BuildCache, digest
    from settings import write_json
    with BuildCache(root, info.path, cancel, log, enabled=resilient, verification=verification) as cache, pending_image(target) as pending_iso:
        work = cache.root
        source_stat = Path(info.path).stat()
        source_key = None
        if resilient:
            log('Проверяем SHA-256 исходника и инструментов для безопасного возобновления…')
            source_key = digest(info.path, cancel)
        tools_key = {name: digest(shutil.which(path) or path, cancel) for name, path in
                     [('ffmpeg', ffmpeg), ('tsmuxer', tsmuxer), ('ffprobe', ffprobe)]} if resilient else {}
        from subtitles import TEXT_CODECS
        subtitle_outputs = [(work / f'subtitle_{i}{".srt" if t["codec"] in TEXT_CODECS else ".sup"}', t)
                            for i, t in enumerate(info.selected_subtitles)]
        subtitle_key = [source_key, tools_key, list(info.selected_subtitles),
                        [digest(t['path'], cancel) for t in info.selected_subtitles if t['source'] == 'external']]
        if not cache.reusable('субтитры', subtitle_key, [p for p, _ in subtitle_outputs]):
            cache.begin('субтитры')
            subtitle_outputs = prepare_subtitles(info, work, ffmpeg, cancel, log, run_command)
            if subtitle_outputs:
                cache.commit('субтитры', subtitle_key, [p for p, _ in subtitle_outputs])
        if subtitle_outputs:
            log(f'Субтитров: {len(subtitle_outputs)}. Отдельные дорожки PGS, без наложения на видео.')
        video = work / 'video.h264'
        audio = [(work / f'audio_{i}.ac3', stream) for i, stream in enumerate(tracks)]
        if copying and not resilient:
            from audio_pipeline import copy_format
            audio = [(p.with_suffix('.'+copy_format(s)[0]), dict(s, output_format=copy_format(s)[0], output_mux=copy_format(s)[1]))
                     if copy_format(s) and info.copy_report.audio_results.get(s.get('index'), {}).get('ok') else (p,s)
                     for p,s in audio]
        if resilient:
            from audio_pipeline import scan_audio, plan_audio
            checks_path = work / 'audio-checks.json'
            checks_key = [source_key, tools_key['ffprobe'], info.selected_audio, 2]
            if cache.reusable('анализ аудио', checks_key, [checks_path]):
                checks = {int(k): v for k, v in json.loads(checks_path.read_text(encoding='utf-8')).items()}
            else:
                cache.begin('анализ аудио')
                log('Проверяем пакеты и синхронизацию выбранных аудиодорожек…')
                checks = scan_audio(info, ffprobe, cancel)
                write_json(checks_path, checks)
                cache.commit('анализ аудио', checks_key, [checks_path])
            audio = plan_audio(info, checks, work, log)
            sound_bps = sum(s['output_bitrate'] for _, s in audio)
            if copying and info.copy_report.video_max_bps + sound_bps > 44_000_000:
                raise DiscForgeError('Суммарный битрейт видео и выбранного звука превышает 44 Мбит/с. Выберите AC-3 для крупных дорожек или перекодирование видео.')
            if not copying:
                average_sound = sum(s.get('output_average_bitrate', s['output_bitrate']) for _, s in audio)
                bitrate = min(bitrate, 44_000_000-sound_bps, int(CAPACITIES[profile]*.93*8/info.duration-average_sound))
                if video_bitrate is not None and bitrate != video_bitrate:
                    raise DiscForgeError(f'Выбранные аудиодорожки ограничивают видео до {bitrate/1e6:.2f} Мбит/с. Уменьшите битрейт общего диска или измените выбор звука; качество автоматически не снижалось.')
                if bitrate < 5_000_000:
                    raise DiscForgeError('Выбранные звуковые дорожки не оставляют места для видео. Выберите AC-3 или BD50.')
        player_peak = None
        if player_profile != 'universal':
            sound_peak = sound_bps if resilient else 640_000 * len(tracks)
            if copying:
                video_peak = getattr(info.copy_report, 'video_max_bps', 0) or 0
                if video_peak == 0:
                    log('GIEC G2805: видео копируется. Пиковый битрейт исходника не измерен; результат нужно проверить на плеере.')
                elif video_peak + sound_peak > G2805_COMBINED_PEAK_TARGET:
                    log('GIEC G2805: пиковый битрейт копируемых потоков выше консервативного ориентира 32 Мбит/с. Видео не изменено; совместимость проверить на плеере.')
            else:
                try:
                    tuned_bitrate, player_peak = encode_targets(player_profile, bitrate, sound_peak)
                except ValueError as exc:
                    raise DiscForgeError(str(exc)) from exc
                if tuned_bitrate != bitrate:
                    log(f'GIEC G2805: битрейт видео ограничен с {bitrate/1e6:.2f} до {tuned_bitrate/1e6:.2f} Мбит/с (экспериментальный режим).')
                    bitrate = tuned_bitrate
                log(f'GIEC G2805: тестовые параметры AVC: {bitrate/1e6:.2f} Мбит/с, maxrate {player_peak/1e6:.2f} Мбит/с.')
        meta = work / 'project.meta'
        def report(stage, fraction):
            if verification:
                verification(None)
            if observer:
                observer(stage, fraction)
        report('encode', 0)
        if not copying:
            log('Видеокодер: ' + ('NVIDIA NVENC' if nvenc else 'CPU x264') + (' · быстрый режим' if fast else ' · сбалансированный режим'))
        def encoded(value):
            progress(value)
            report('encode', value/90)
        encode_key = [source_key, tools_key, selected_mode, bitrate, nvenc, fast, gpu_frames, info.selected_audio,
                      info.audio_modes, [(str(p.name), s) for p, s in audio], 1] + ([player_profile] if player_profile != 'universal' else [])
        encoded_paths = [video, *(p for p, _ in audio)]
        from truehd_audio import paths as truehd_paths, interleave
        for p, s in audio:
            if s.get('output_codec') == 'truehd':
                encoded_paths.extend(truehd_paths(p))
        encode_start = time.monotonic()
        reused_encode = cache.reusable('видео и аудио', encode_key, encoded_paths)
        if not reused_encode:
            cache.begin('видео и аудио')
            command = make_copy_command(ffmpeg, info, video, audio if not resilient else [], selected_mode == 'video_copy') if copying else make_encode_command(ffmpeg, info, video, audio if not resilient else [], bitrate, nvenc, fast)
            if resilient:
                if not copying:
                    command[command.index('-maxrate')+1] = str(min(30_000_000, 44_000_000-sound_bps))
            if player_peak is not None and not copying:
                command[command.index('-maxrate')+1] = str(player_peak)
                command[command.index('-bufsize')+1] = str(player_peak)
            if resilient:
                if nvenc and gpu_frames and not copying:
                    from gpu_pipeline import supported, cuda_command
                    if supported(info, ffmpeg, cancel, log, run_command, make_video_command):
                        command = cuda_command(command)
                from audio_pipeline import append_audio
                command = append_audio(command, audio, info)
            run_command(command,
                    ('Копирование видео + AC-3' if selected_mode == 'video_copy' else 'Копирование потоков') if copying else ('Кодирование видео и звука' if audio else 'Кодирование видео'),
                    0, 90, info.duration, cancel, log, encoded)
            for p, s in audio:
                if s.get('output_codec') == 'truehd':
                    log('Подготавливаем TrueHD/Atmos для Blu-ray без изменения основного потока…')
                    interleave(p, cancel)
            current_stat = Path(info.path).stat()
            if (source_stat.st_size, source_stat.st_mtime_ns) != (current_stat.st_size, current_stat.st_mtime_ns):
                raise DiscForgeError('Исходник изменился во время обработки. Этап не сохранён.')
            if resilient:
                log('Видео и звук подготовлены. Проверяем SHA-256 готовых потоков и сохраняем этап; GPU больше не требуется…')
            cache.commit('видео и аудио', encode_key, encoded_paths, time.monotonic()-encode_start)
        encoded(90)
        report('encode', 1)
        if copying and signature_changed(info, cancel):
            raise DiscForgeError('Файл изменился при копировании. Сборка остановлена.')
        write_meta(meta, video, audio, chapters, fps=info.copy_report.fps if copying else '23.976',
                   subtitles=subtitle_outputs, width=info.width if copying else 1920, height=info.height if copying else 1080)
        if cancel.is_set():
            raise DiscForgeError('Операция отменена пользователем.')
        # Author to an intermediate output first; move to destination only on success.
        author_target = pending_iso if iso and menu is None and not resilient else work / 'disc'
        authored_key = [encode_key, list(chapters) if chapters is not None else None, menu.to_dict() if menu else None,
                        [(t, digest(p, cancel)) for p, t in subtitle_outputs],
                        # The menu already contains the embedded PNG (base64).
                        # It is content-hashed with the design, never a file path.
                        digest(Path(__file__).parent/'assets/bdj/menu.jar', cancel) if menu else None,
                        digest(meta, cancel), 2]
        from disc_menu import theme_background_path
        if menu and not menu.background and theme_background_path(menu.theme):
            authored_key.append(digest(theme_background_path(menu.theme), cancel))
        reused_disc = cache.reusable('диск и меню', authored_key, [author_target])
        log('Формирование структуры Blu-ray через tsMuxer...')
        report('mux', 0)
        if not reused_disc:
            cache.begin('диск и меню')
            if resilient and author_target.exists():
                # Only this fixed child of the verified cache directory is removed.
                if author_target.resolve() != (cache.root.resolve() / 'disc'):
                    raise DiscForgeError('Некорректный рабочий каталог диска.')
                shutil.rmtree(author_target)
            if observer:
                run_tsmuxer(tsmuxer, meta, author_target, cancel, log,
                        progress=lambda f: (progress(90+3*f), report('mux', f)))
            else:
                run_tsmuxer(tsmuxer, meta, author_target, cancel, log)
        report('mux', 1)
        report('menu', 0)
        if cancel.is_set():
            raise DiscForgeError('Операция отменена пользователем.')
        if not author_target.exists():
            raise DiscForgeError('tsMuxer не создал выходной файл/папку.')
        if menu is not None:
            log('Создаём интерактивное меню BD-J…')
            from disc_audio import bind_tracks, menu_tracks
            menu = bind_tracks(menu, author_target / 'BDMV/PLAYLIST/00000.mpls', menu_tracks(info))
            from disc_audio import bind_subtitles
            menu = bind_subtitles(menu, author_target / 'BDMV/PLAYLIST/00000.mpls', menu_subtitles(info))
            if not reused_disc:
                install_menu(author_target, menu, list(chapters))
            progress(94)
        if iso and menu is None and not resilient:
            size = author_target.stat().st_size
        else:
            size = sum(f.stat().st_size for f in author_target.rglob('*') if f.is_file())
            if not (author_target / 'BDMV').is_dir():
                raise DiscForgeError('tsMuxer не создал каталог BDMV.')
        if size > CAPACITIES[profile]:
            raise DiscForgeError(f'Размер результата {size / 1e9:.2f} ГБ превышает {profile}. Файлы болванки не затронуты.')
        # Validate the authored folder before packaging and before publishing.
        if not iso or menu is not None or resilient:
            bdmv_report = inspect_bdmv(author_target, profile)
            if not bdmv_report.structurally_valid:
                raise DiscForgeError('Проверка BDMV не пройдена: ' + '; '.join(bdmv_report.errors[:8]))
            log('Структурная проверка BDMV пройдена; совместимость с плеером не подтверждена.')
        validation = None
        if resilient:
            from disc_verify import verify_disc
            validation = verify_disc(author_target, info, audio, subtitle_outputs, chapters, menu, ffprobe, cancel, log, ffmpeg=ffmpeg, verification=verification)
            validation['source'] = source_key
            validation['processing_mode'] = selected_mode
            validation['audio'] = [{'index': s.get('index'), 'copy': s['output_copy'], 'format': s['output_mux']} for _, s in audio]
            validation['reused_encode'] = reused_encode
            validation['reused_disc'] = reused_disc
            if not reused_disc:
                cache.commit('диск и меню', authored_key, [author_target])
        if keep_authored:
            write_json(work / 'collection-title-verification.json', validation)
            return author_target
        report('menu', 1)
        if (menu is not None or resilient) and iso:
            image = work / 'image.iso' if resilient else pending_iso
            report('iso', 0)
            image_key = [authored_key, profile, tools_key, digest(Path(__file__).parent/'tools/windows_iso.ps1', cancel)]
            if not cache.reusable('ISO', image_key, [image]):
                cache.begin('ISO')
                if resilient and image.exists():
                    image.unlink()
                create_iso(author_target, image, CAPACITIES[profile], cancel, log,
                           progress=lambda f: (progress(94+5*f), report('iso', f)))
                preliminary = inspect_iso(image, profile)
                if not preliminary.valid:
                    raise DiscForgeError('Созданный ISO не прошёл UDF-проверку: ' + '; '.join(preliminary.errors[:8]))
                cache.commit('ISO', image_key, [image])
            report('iso', 1)
            author_target = image
            size = image.stat().st_size
        report('verify', 0)
        if iso:
            iso_report = inspect_iso(author_target, profile)
            if not iso_report.valid:
                raise DiscForgeError('Проверка ISO UDF 2.50 не пройдена: ' + '; '.join(iso_report.errors[:8]))
            log('Метаданные UDF 2.50 проверены; воспроизведение требует отдельного теста.')
        if resilient:
            if iso:
                from disc_verify import verify_image_payload
                from verification_progress import VerificationProgress
                tracker = VerificationProgress(sum(f['size'] for f in validation['files'].values()) + size,
                                               len(validation['files']) + 1, verification, scope='iso-final')
                log('Проверяем содержимое ISO: подключаем только для чтения и сверяем SHA-256…')
                try:
                    verify_image_payload(author_target, validation['files'], cancel, tracker)
                except ValueError:
                    cache.begin('ISO')
                    raise
                validation['iso'] = tracker.digest(author_target, cancel, '2/2 · Контрольная сумма ISO')
                validation['iso_payload_verified'] = True
                tracker.finish()
            report_file = target.with_name(target.name + '.verification.json')
            write_json(report_file, validation)
            summary = ('DiskForge — отчёт проверки\n\n'
                       'Проверки структуры и связей пройдены.\n'
                       f'Режим видео: {selected_mode}\n'
                       f'Аудиодорожки: {len(audio)} · Субтитры: {len(subtitle_outputs)} · Главы: {validation["chapters"]}\n'
                       f'Повторно использованы видео/аудио: {"да" if reused_encode else "нет"}\n'
                       f'Повторно использованы диск/меню: {"да" if reused_disc else "нет"}\n'
                       + (f'TrueHD/Atmos: {len(validation["lossless_truehd"])} дорожек побитно сверены с исходником; совместимый AC-3 проверен.\n' if validation.get('lossless_truehd') else '')
                       + ('Содержимое ISO сверено с файлами BDMV по SHA-256.\nSHA-256 ISO: ' + validation['iso']['sha256'] + '\n' if iso else '')
                       + '\nПолный список контрольных сумм: ' + report_file.name
                       + '\nВоспроизведение и работа пульта на бытовом проигрывателе этим тестом не проверяются.\n')
            target.with_name(target.name + '.verification.txt').write_text(summary, encoding='utf-8-sig')
            log('Отчёт проверки: ' + str(report_file))
        if cancel.is_set():
            raise DiscForgeError('Операция отменена пользователем.')
        shutil.move(str(author_target), str(target))
        if resilient:
            # Keep expensive intermediates for later edits and retries; explicit UI cleanup is available.
            log('Кэш этапов сохранён. Его можно удалить после проверки готового диска.')
        report('verify', 1)
        progress(100)
        log(f'Готово: {target} ({size/1e9:.2f} ГБ).')
        return target
