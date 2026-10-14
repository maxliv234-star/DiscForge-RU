"""Author a collection from individually validated title checkpoints.

Only one-clip playlists produced by our tsMuxer pipeline are accepted. Streams
are never rewritten. Playlist clip IDs and their backup copies are rebound.
"""
from dataclasses import replace
from pathlib import Path
import json
import os
import re
import shutil
import struct
import tempfile
import zipfile


def rebind_playlist(payload, clip):
    data = bytearray(payload)
    if len(data) < 40 or data[:8] != b'MPLS0200' or not re.fullmatch(r'\d{5}', clip):
        raise ValueError('Неподдерживаемый плейлист коллекции.')
    start = struct.unpack_from('>I', data, 8)[0]
    if start < 40 or start+12 > len(data):
        raise ValueError('Повреждённый заголовок плейлиста.')
    length = struct.unpack_from('>I', data, start)[0]
    count, subpaths = struct.unpack_from('>HH', data, start+6)
    item = start+10
    item_size = struct.unpack_from('>H', data, item)[0]
    if (count != 1 or subpaths or item_size < 32 or item+2+item_size > start+4+length
            or start+4+length > len(data) or data[item+2:item+11] != b'00000M2TS'
            or data[item+12] & 0x10):
        raise ValueError('Коллекция поддерживает только один клип без дополнительных ракурсов на фильм.')
    data[item+2:item+7] = clip.encode('ascii')
    return bytes(data)


def _png(image):
    from PySide6.QtCore import QBuffer, QIODevice
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise ValueError('Не удалось сохранить изображение меню.')
    return bytes(buffer.data())


def merge_menu(root, sources, design, titles):
    from disc_menu import render_page, page_elements, focus_patch, bdjo_bytes, index_bytes
    root_pages = (len(sources)+4)//5
    offsets, configs, cursor = [], [], root_pages
    for source in sources:
        with zipfile.ZipFile(source/'BDMV/JAR/00000.jar') as jar:
            props = dict(line.split('=', 1) for line in jar.read('menu.properties').decode('ascii').splitlines() if '=' in line)
        offsets.append(cursor)
        configs.append(props)
        cursor += int(props['pages'])
    props = {'pages': str(cursor), 'movies': str(len(sources)), 'playlist': '00000', 'audio.count': '0', 'subtitle.count': '0'}
    bdmv = root/'BDMV'
    for directory in ('JAR', 'BDJO', 'BACKUP/JAR', 'BACKUP/BDJO'):
        (bdmv/directory).mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(Path(__file__).parent/'assets/bdj/menu.jar') as engine, zipfile.ZipFile(bdmv/'JAR/00000.jar', 'w', zipfile.ZIP_DEFLATED) as out:
        for name in engine.namelist():
            out.writestr(name, engine.read(name))
        for page in range(root_pages):
            from collection_menu import catalog_page
            root_design, entries = catalog_page(design, titles, page, offsets)
            base = render_page(root_design, [0.0], entries_override=entries)
            out.writestr(f'page{page}.png', _png(base))
            props[f'page.{page}.count'] = str(len(entries))
            for element in page_elements(root_design, [0.0], 0, entries):
                if not element['button']:
                    continue
                i = element['index']
                prefix = f'page.{page}.{i}'
                props[prefix] = entries[i][1]
                patch, x, y = focus_patch(base, element)
                name = f'focus{page}_{i}.png'
                out.writestr(name, _png(patch))
                props.update({prefix+'.focus': name, prefix+'.focusX': str(x), prefix+'.focusY': str(y)})
        for movie, (source, offset, cfg) in enumerate(zip(sources, offsets, configs)):
            prefix = f'movie.{movie}.'
            props[prefix+'playlist'] = f'{movie:05}'
            props[prefix+'home'] = str(offset)
            for key in ('audio.count', 'subtitle.count'):
                props[prefix+key] = cfg[key]
            for key in ('audio.page', 'subtitle.page'):
                props[prefix+key] = str(offset+int(cfg[key]))
            with zipfile.ZipFile(source/'BDMV/JAR/00000.jar') as jar:
                for page in range(int(cfg['pages'])):
                    target = page+offset
                    props[f'page.{target}.movie'] = str(movie)
                    out.writestr(f'page{target}.png', jar.read(f'page{page}.png'))
                    old = f'page.{page}.'
                    for key, value in cfg.items():
                        if not key.startswith(old):
                            continue
                        tail = key[len(old):]
                        if tail.isdigit() and value.startswith('page:'):
                            value = 'page:'+str(offset+int(value[5:]))
                        if tail.endswith('.focus'):
                            name = f'movie{movie}_{value}'
                            out.writestr(name, jar.read(value))
                            value = name
                        props[f'page.{target}.{tail}'] = value
        out.writestr('menu.properties', '\n'.join(f'{k}={v}' for k, v in props.items()).encode('ascii'))
        out.writestr('discforge-collection.json', json.dumps({'version': 1, 'titles': titles, 'design': design.to_dict()}, ensure_ascii=False).encode('utf-8'))
    (bdmv/'BDJO/00000.bdjo').write_bytes(bdjo_bytes())
    (bdmv/'index.bdmv').write_bytes(index_bytes())
    for name in ('BDJO/00000.bdjo', 'JAR/00000.jar', 'index.bdmv'):
        shutil.copyfile(bdmv/name, bdmv/'BACKUP'/name)
    import hashlib
    identity = hashlib.sha256((bdmv/'JAR/00000.jar').read_bytes()).digest()[:16]
    cert = b'BDID0200'+bytes(32)+struct.pack('>I', 0xffff0001)+identity
    (root/'CERTIFICATE/BACKUP').mkdir(parents=True, exist_ok=True)
    for name in ('id.bdmv', 'BACKUP/id.bdmv'):
        (root/'CERTIFICATE'/name).write_bytes(cert)
    validate_menu(root, props, offsets, configs)


def validate_menu(root, props, offsets, configs):
    """Check every action in its movie context, including cross-title boundaries."""
    with zipfile.ZipFile(root/'BDMV/JAR/00000.jar') as jar:
        names = set(jar.namelist())
        for page in range(int(props['pages'])):
            if f'page{page}.png' not in names:
                raise ValueError('Отсутствует страница коллекции.')
            movie = props.get(f'page.{page}.movie')
            for i in range(int(props[f'page.{page}.count'])):
                key = f'page.{page}.{i}'
                if props[key+'.focus'] not in names:
                    raise ValueError('Отсутствует выделение кнопки.')
                kind, value = props[key].split(':')
                number = int(value)
                if kind == 'page':
                    valid = 0 <= number < int(props['pages'])
                    if movie is not None:
                        valid = valid and offsets[int(movie)] <= number < offsets[int(movie)]+int(configs[int(movie)]['pages'])
                elif movie is not None:
                    limit = int(configs[int(movie)].get(kind+'.count', '0'))
                    if kind == 'play':
                        from disc_menu import validate_menu_chapters
                        # Original title validation proved each chapter action. Require the unchanged action.
                        valid = props[key] in configs[int(movie)].values()
                    else:
                        valid = kind in ('audio', 'sub') and 0 <= number <= (int(configs[int(movie)]['subtitle.count']) if kind == 'sub' else limit)
                else:
                    valid = False
                if not valid:
                    raise ValueError('Некорректная ссылка кнопки коллекции: '+props[key])


def create_collection(jobs, config, profile, as_iso, nvenc, cancel, log, progress, menu_for,
                      *, bitrate=12_000_000, modes=None, fast=True, verification=None, timing=None):
    from core import create_bluray, CAPACITIES, unique_target
    from disc_capacity import estimate, require_fit
    from bdmv_preflight import inspect
    from windows_iso import create_iso, pending_image
    from disc_verify import verify_image_payload
    from verification_progress import VerificationProgress
    from tools.iso_udf_preflight import inspect as inspect_iso
    from settings import write_json
    if not jobs or len(jobs) > 99:
        raise ValueError('На общем диске поддерживается от 1 до 99 фильмов.')
    from collection_titles import normalize_names, movie_title
    names = normalize_names(config.get('movie_names', {}), [media.path for media, _ in jobs])
    titles = [movie_title(media.path, names) for media, _ in jobs]
    from bitrate_advisor import normalize_rates
    rates = normalize_rates(config.get('video_rates', {}), [media.path for media, _ in jobs])
    modes = modes or ['auto']*len(jobs)
    if len(modes) != len(jobs) or any(mode not in ('auto', 'copy', 'video_copy', 'encode') for mode in modes):
        raise ValueError('Режим обработки должен быть задан для каждого фильма.')
    budgets = [estimate([job], profile, mode, collection=True, bitrate=bitrate, rates=rates) for job, mode in zip(jobs, modes)]
    from disc_capacity import Budget
    budget = Budget(CAPACITIES[profile], *(sum(getattr(b, field) for b in budgets) for field in ('video', 'audio', 'subtitles', 'overhead')), tuple(row for b in budgets for row in b.titles))
    budget = replace(budget, overhead=budget.overhead-(len(jobs)-1)*40_000_000)
    require_fit(budget)
    log(budget.explanation())
    root = Path(config['output'])
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < budget.total*3:
        raise ValueError(f'Для временных потоков и результата требуется до {budget.total*3/1e9:.1f} ГБ свободного места на рабочем диске.')
    sources = []
    reports = []
    design = menu_for(*jobs[0])
    if design is None:
        raise ValueError('Для общего диска включите интерактивное меню выбора фильма.')
    for i, ((media, chapters), mode) in enumerate(zip(jobs, modes)):
        log(f'Коллекция: фильм {i+1}/{len(jobs)} · {media.name}')
        film_design = replace(menu_for(media, chapters), title=titles[i])
        source = create_bluray(media, profile, str(root), config['ffmpeg'], config['tsmuxer'], False, nvenc,
            cancel, log, lambda v: progress((i+v/100)*85/len(jobs)), chapters=chapters, menu=film_design,
            fast=fast, processing_mode=mode, ffprobe=config.get('ffprobe', 'ffprobe'), resilient=True,
            gpu_frames=config.get('gpu_frames', True), verification=verification, video_bitrate=rates.get(str(Path(media.path).resolve()), bitrate), keep_authored=True,
            player_profile=config.get('player_profile', 'universal'),
            observer=(lambda stage, fraction: timing(f'Фильм {i+1}/{len(jobs)} · {stage}', -1)) if timing else None)
        sources.append(source)
        reports.append(json.loads((source.parent/'collection-title-verification.json').read_text(encoding='utf-8')))
    target = unique_target(root, design.title or 'Коллекция', as_iso)
    with tempfile.TemporaryDirectory(prefix='.collection-', dir=root) as temp, pending_image(target) as pending:
        combined = Path(temp)/'disc'
        combined.mkdir()
        # Copy small metadata from the first validated title; no stale title assets.
        for relative in ('BDMV/MovieObject.bdmv', 'BDMV/BACKUP/MovieObject.bdmv'):
            dest = combined/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sources[0]/relative, dest)
        for i, source in enumerate(sources):
            if cancel.is_set():
                raise ValueError('Сборка отменена.')
            stem = f'{i:05}'
            for directory, suffix in (('STREAM', '.m2ts'), ('CLIPINF', '.clpi'), ('PLAYLIST', '.mpls')):
                original = source/f'BDMV/{directory}/00000{suffix}'
                dest = combined/f'BDMV/{directory}/{stem}{suffix}'
                dest.parent.mkdir(parents=True, exist_ok=True)
                if suffix == '.mpls':
                    dest.write_bytes(rebind_playlist(original.read_bytes(), stem))
                elif suffix == '.m2ts':
                    # Same output volume: hardlink avoids a full film copy; never modify the linked stream.
                    try:
                        os.link(original, dest)
                    except OSError:
                        if shutil.disk_usage(combined).free < original.stat().st_size+budget.total:
                            raise ValueError('Файловая система не поддерживает быстрые ссылки. Недостаточно места для копии фильма и ISO.')
                        log('Копируем подготовленный фильм: файловая система не поддерживает жёсткие ссылки.')
                        with original.open('rb') as src, dest.open('xb') as dst:
                            while block := src.read(4*1024*1024):
                                if cancel.is_set():
                                    raise ValueError('Сборка отменена.')
                                dst.write(block)
                else:
                    shutil.copyfile(original, dest)
                if directory != 'STREAM':
                    backup = combined/f'BDMV/BACKUP/{directory}/{stem}{suffix}'
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(dest, backup)
        merge_menu(combined, sources, design, titles)
        checked = inspect(combined, profile)
        if not checked.structurally_valid:
            raise ValueError('Проверка общего диска: '+'; '.join(checked.errors[:8]))
        if checked.size_bytes+32_000_000 > CAPACITIES[profile]:
            raise ValueError(f'Фактический размер с резервом UDF {checked.size_bytes/1e9+.032:.2f} ГБ превышает {profile}. Уменьшите состав диска. Подготовленные фильмы сохранены в кэше.')
        files = [p for p in sorted(combined.rglob('*')) if p.is_file()]
        tracker = VerificationProgress(sum(p.stat().st_size for p in files), len(files), verification)
        hashes = {p.relative_to(combined).as_posix(): tracker.digest(p, cancel, 'Проверка общего диска') for p in files}
        tracker.finish()
        # Prove the combined streams are exactly the individually verified streams.
        for i, report in enumerate(reports):
            if hashes[f'BDMV/STREAM/{i:05}.m2ts'] != report['files']['BDMV/STREAM/00000.m2ts']:
                raise ValueError('Поток фильма изменился при сборке коллекции.')
        result = dict(passed=True, collection=True, titles=titles, files=hashes, title_reports=reports,
                      hardware_player_tested=False, playback_tested=False)
        if as_iso:
            if timing:
                timing('Создание общего ISO', -1)
            create_iso(combined, pending, CAPACITIES[profile], cancel, log, progress=lambda f: progress(85+14*f))
            iso_report = inspect_iso(pending, profile)
            if not iso_report.valid:
                raise ValueError('Проверка UDF: '+'; '.join(iso_report.errors))
            tracker = VerificationProgress(sum(v['size'] for v in hashes.values())+pending.stat().st_size,
                                           len(hashes)+1, verification, scope='iso-final')
            verify_image_payload(pending, hashes, cancel, tracker)
            result['iso'] = tracker.digest(pending, cancel, 'Контрольная сумма общего ISO')
            result['iso_payload_verified'] = True
            tracker.finish()
        if cancel.is_set():
            raise ValueError('Сборка отменена.')
        shutil.move(str(pending if as_iso else combined), str(target))
        write_json(target.with_name(target.name+'.verification.json'), result)
    progress(100)
    log('Готов общий диск: '+str(target))
    return target
