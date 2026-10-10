"""DiscForge RU: cross-platform desktop alpha, requires PySide6 and external tools.

The alpha creates chapter-enabled BDMV/ISO but deliberately does NOT claim menu authoring.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QSplitter, QStatusBar, QTabWidget, QVBoxLayout,
    QWidget,
)

from core import (CAPACITIES, SUPPORTED, DiscForgeError, MediaInfo,
                  create_bluray, probe_media)
from settings import load as load_settings, save as save_settings

VERSION = '0.1.0-alpha'


def timecode(seconds: float) -> str:
    n = round(seconds)
    hours, minutes = divmod(n, 3600)
    minutes, secs = divmod(minutes, 60)
    return f'{hours:02}:{minutes:02}:{secs:02}'


def parse_timecode(code: str) -> float:
    parts = code.strip().split(':')
    if len(parts) != 3:
        raise ValueError('Формат времени: ЧЧ:ММ:СС')
    h, m, s = (int(p) for p in parts)
    if min(h, m, s) < 0 or m > 59 or s > 59:
        raise ValueError('Недопустимое время')
    return float(h * 3600 + m * 60 + s)


class ScanThread(QThread):
    result = Signal(str, object, str)

    def __init__(self, paths: list[str], probe: str):
        super().__init__()
        self.paths = paths
        self.probe = probe

    def run(self) -> None:
        for path in self.paths:
            try:
                self.result.emit(path, probe_media(path, self.probe), '')
            except Exception as exc:  # user-supplied corrupt media must not crash UI
                self.result.emit(path, None, str(exc))


class BuildThread(QThread):
    message = Signal(str)
    progress_changed = Signal(int)
    item_started = Signal(str)
    item_done = Signal(str, str)
    failed = Signal(str, str)
    finished_all = Signal(bool)

    def __init__(self, jobs: list[tuple[MediaInfo, list[float]]], config: dict, profile: str,
                 as_iso: bool, nvenc: bool):
        super().__init__()
        self.jobs = jobs
        self.config = config
        self.profile = profile
        self.as_iso = as_iso
        self.nvenc = nvenc
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        all_successful = True
        for i, (media, chapters) in enumerate(self.jobs, 1):
            if self.cancel_event.is_set():
                all_successful = False
                break
            self.item_started.emit(media.path)
            self.message.emit(f'[{i}/{len(self.jobs)}] {media.name}')
            try:
                target = create_bluray(
                    media, self.profile, self.config['output'], self.config['ffmpeg'],
                    self.config['tsmuxer'], self.as_iso, self.nvenc,
                    self.cancel_event, self.message.emit, self.progress_changed.emit,
                    chapters=chapters,
                )
                self.item_done.emit(media.path, str(target))
            except Exception as exc:
                all_successful = False
                self.failed.emit(media.path, str(exc))
                if self.cancel_event.is_set():
                    break
        self.finished_all.emit(all_successful and not self.cancel_event.is_set())


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('DiscForge RU — мастер Blu-ray | ' + VERSION)
        self.resize(1190, 760)
        self.setMinimumSize(920, 620)
        self.media: dict[str, MediaInfo] = {}
        self.chapters: dict[str, list[float]] = {}
        self.scan_thread: ScanThread | None = None
        self.build_thread: BuildThread | None = None
        self._build_ui()
        self._restore()
        self._refresh_buttons()

    def _build_ui(self) -> None:
        host = QWidget()
        self.setCentralWidget(host)
        root = QVBoxLayout(host)
        root.setSpacing(12)
        root.setContentsMargins(18, 16, 18, 12)

        header = QHBoxLayout()
        heading = QLabel('◆  DiscForge <span style="color:#67a9ff">RU</span>')
        heading.setTextFormat(Qt.RichText)
        heading.setObjectName('brand')
        header.addWidget(heading)
        header.addStretch()
        tag = QLabel('OPEN SOURCE  ·  ALPHA 0.1')
        tag.setObjectName('tag')
        header.addWidget(tag)
        root.addLayout(header)

        warning = QLabel('ВЕРСИЯ ALPHA: создаёт структуру Blu-ray с главами, но пока БЕЗ интерактивного меню. '
                         'BD-J / HDMV и совместимость с бытовыми плеерами находятся в разработке.')
        warning.setWordWrap(True)
        warning.setObjectName('warning')
        root.addWidget(warning)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)
        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 4, 0)
        left_box.addWidget(QLabel('ФИЛЬМЫ В ПРОЕКТЕ'))
        self.movies = QListWidget()
        self.movies.currentItemChanged.connect(lambda *_: self._select_media())
        left_box.addWidget(self.movies, 1)
        line = QHBoxLayout()
        self.add_button = QPushButton('＋ Добавить видео')
        self.add_button.clicked.connect(self.add_media)
        self.remove_button = QPushButton('Удалить')
        self.remove_button.clicked.connect(self.remove_media)
        line.addWidget(self.add_button, 1)
        line.addWidget(self.remove_button)
        left_box.addLayout(line)
        self.details = QLabel('Добавьте MKV, MP4, MOV или другой видеофайл для анализа.')
        self.details.setObjectName('details')
        self.details.setWordWrap(True)
        self.details.setMinimumHeight(90)
        left_box.addWidget(self.details)
        splitter.addWidget(left)

        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)
        splitter.setSizes([450, 690])

        build_tab = QWidget()
        build_box = QVBoxLayout(build_tab)
        build_box.setSpacing(12)
        profile_box = QGroupBox('Параметры Blu-ray')
        form = QFormLayout(profile_box)
        self.profile = QComboBox()
        self.profile.addItems(sorted(CAPACITIES))
        self.profile.setCurrentText('BD25')
        form.addRow('Ёмкость носителя:', self.profile)
        self.output_mode = QComboBox()
        self.output_mode.addItems(['ISO-образ', 'Папка BDMV'])
        form.addRow('Формат результата:', self.output_mode)
        self.encoder = QComboBox()
        self.encoder.addItems(['CPU x264 — надёжнее', 'NVIDIA NVENC — быстрее, экспериментально'])
        form.addRow('Видеокодер:', self.encoder)
        build_box.addWidget(profile_box)

        path_box = QGroupBox('Инструменты и выходная папка')
        paths = QFormLayout(path_box)
        self.path_fields: dict[str, QLineEdit] = {}
        for key, label in [
            ('ffmpeg', 'ffmpeg:'), ('ffprobe', 'ffprobe:'),
            ('tsmuxer', 'tsMuxer:'), ('output', 'Готовые диски:'),
        ]:
            edit = QLineEdit()
            self.path_fields[key] = edit
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            browse = QPushButton('…')
            browse.setFixedWidth(36)
            browse.clicked.connect(lambda _=False, k=key: self._choose_path(k))
            row.addWidget(browse)
            paths.addRow(label, row)
        build_box.addWidget(path_box)
        info = QLabel('Выход: видео H.264 1080p 23,976 кадр/с + первая аудиодорожка AC-3. '
                      'Субтитры и остальные аудиодорожки пока не переносятся. '
                      'Сначала проверьте ISO на программном проигрывателе и бытовом плеере.')
        info.setWordWrap(True)
        info.setObjectName('hint')
        build_box.addWidget(info)
        build_box.addStretch()
        self.tabs.addTab(build_tab, 'Сборка')

        chapter_tab = QWidget()
        chapter_box = QVBoxLayout(chapter_tab)
        chapter_box.addWidget(QLabel('Точки перехода между главами для выбранного фильма'))
        self.chapter_list = QListWidget()
        chapter_box.addWidget(self.chapter_list, 1)
        chapter_actions = QHBoxLayout()
        self.auto_interval = QSpinBox()
        self.auto_interval.setRange(1, 60)
        self.auto_interval.setValue(10)
        self.auto_interval.setSuffix(' мин')
        chapter_actions.addWidget(self.auto_interval)
        autogen = QPushButton('Автоматически')
        autogen.clicked.connect(self.auto_chapters)
        chapter_actions.addWidget(autogen)
        manual = QPushButton('＋ Глава')
        manual.clicked.connect(self.add_chapter)
        chapter_actions.addWidget(manual)
        delete = QPushButton('Убрать')
        delete.clicked.connect(self.remove_chapter)
        chapter_actions.addWidget(delete)
        chapter_box.addLayout(chapter_actions)
        note = QLabel('Первая глава всегда начинается с 00:00:00. '
                      'При сборке используется параметр tsMuxer --custom-chapters.')
        note.setObjectName('hint')
        note.setWordWrap(True)
        chapter_box.addWidget(note)
        self.tabs.addTab(chapter_tab, 'Главы')

        menu_tab = QWidget()
        menu_box = QVBoxLayout(menu_tab)
        menu_box.setSpacing(12)
        title = QLabel('Конструктор меню — следующий этап разработки')
        title.setObjectName('section')
        menu_box.addWidget(title)
        menu_box.addWidget(QLabel('Здесь появятся: главный экран, выбор глав, звука, субтитров, '
                                  'оформление кнопок и навигация с пульта.'))
        self.menu_title = QLineEdit('Моя коллекция Blu-ray')
        menu_box.addWidget(QLabel('Название проекта (сохраняется в .dfr.json):'))
        menu_box.addWidget(self.menu_title)
        support = QLabel('ВНИМАНИЕ: поле выше пока только метаданные проекта. '
                         'Оно не записывает меню на диск. Мы не выдаём ISO без меню за готовый релиз.')
        support.setWordWrap(True)
        support.setObjectName('warning')
        menu_box.addWidget(support)
        menu_box.addStretch()
        self.tabs.addTab(menu_tab, 'Меню (план)')

        logbar = QHBoxLayout()
        logbar.addWidget(QLabel('ЖУРНАЛ РАБОТЫ'))
        logbar.addStretch()
        clear = QPushButton('Очистить')
        clear.clicked.connect(lambda: self.log.clear())
        logbar.addWidget(clear)
        root.addLayout(logbar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(125)
        self.log.setPlaceholderText('Ожидание действий…')
        root.addWidget(self.log)
        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        footer.addWidget(self.progress, 1)
        self.cancel_button = QPushButton('Отмена')
        self.cancel_button.clicked.connect(self.cancel_build)
        footer.addWidget(self.cancel_button)
        self.build_button = QPushButton('▶  СОЗДАТЬ BLU-RAY')
        self.build_button.setObjectName('primary')
        self.build_button.clicked.connect(self.start_build)
        footer.addWidget(self.build_button)
        root.addLayout(footer)
        self.setStatusBar(QStatusBar())

        project = self.menuBar().addMenu('Проект')
        for text, callback in [('Новый', self.new_project), ('Открыть проект…', self.open_project),
                               ('Сохранить проект…', self.save_project)]:
            action = QAction(text, self)
            action.triggered.connect(callback)
            project.addAction(action)
        help_menu = self.menuBar().addMenu('Справка')
        about = QAction('О программе', self)
        about.triggered.connect(self.about)
        help_menu.addAction(about)

    def _restore(self) -> None:
        for key, val in load_settings().items():
            self.path_fields[key].setText(val)

    def _config(self) -> dict[str, str]:
        return {key: edit.text().strip() for key, edit in self.path_fields.items()}

    def _save_config(self) -> None:
        save_settings(self._config())

    def _choose_path(self, key: str) -> None:
        if key == 'output':
            path = QFileDialog.getExistingDirectory(self, 'Куда сохранять Blu-ray?')
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Путь к ' + key,
                          filter=('Все файлы (*)' if sys.platform == 'darwin' else 'Исполняемые файлы (*.exe);;Все файлы (*)'))
        if path:
            self.path_fields[key].setText(path)
            self._save_config()

    def add_media(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, 'Выберите видео', '',
                    'Видео (*.mkv *.mp4 *.mov *.m2ts *.mts *.ts *.avi);;Все файлы (*)')
        self._queue_scan(paths)

    def _queue_scan(self, paths: list[str]) -> None:
        paths = [str(Path(p).resolve()) for p in paths if Path(p).suffix.lower() in SUPPORTED]
        existing = {self.movies.item(i).data(Qt.UserRole) for i in range(self.movies.count())}
        fresh = [p for p in dict.fromkeys(paths) if p not in existing]
        if not fresh:
            return
        if self.scan_thread and self.scan_thread.isRunning():
            QMessageBox.information(self, 'Идёт анализ', 'Дождитесь окончания анализа предыдущих файлов.')
            return
        for path in fresh:
            item = QListWidgetItem('⏳  ' + Path(path).name)
            item.setData(Qt.UserRole, path)
            self.movies.addItem(item)
        self.scan_thread = ScanThread(fresh, self.path_fields['ffprobe'].text().strip())
        self.scan_thread.result.connect(self._scanned)
        self.scan_thread.finished.connect(self._refresh_buttons)
        self.scan_thread.start()
        self._refresh_buttons()
        self._message(f'Анализируем {len(fresh)} файлов…')

    def _scanned(self, path: str, info: MediaInfo | None, error: str) -> None:
        for i in range(self.movies.count()):
            item = self.movies.item(i)
            if item.data(Qt.UserRole) == path:
                item.setText(('✅  ' if info else '❌  ') + Path(path).name)
                item.setToolTip(error if error else path)
                break
        if info:
            self.media[path] = info
            self.chapters.setdefault(path, [0.0])
            self._message(f'OK: {info.name} — {timecode(info.duration)}; {info.width}×{info.height}')
        else:
            self._message(f'ОШИБКА {Path(path).name}: {error}')
        self._select_media()
        self._refresh_buttons()

    def _selected_path(self) -> str | None:
        item = self.movies.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _select_media(self) -> None:
        path = self._selected_path()
        info = self.media.get(path or '')
        self.chapter_list.clear()
        if not info:
            self.details.setText('Выберите успешно проанализированный фильм.')
        else:
            self.details.setText(
                f'{info.name}\n{timecode(info.duration)}  •  {info.size/1e9:.2f} ГБ  •  '
                f'{info.width}×{info.height}  •  {info.video_codec.upper()}\n'
                f'Аудиодорожек: {info.audio_tracks}; субтитров: {info.subtitle_tracks}; '
                f'HDR: {"да (UHD-модуль ещё не готов)" if info.is_hdr else "нет"}'
            )
            for t in self.chapters.get(path, [0.0]):
                item = QListWidgetItem(timecode(t))
                item.setData(Qt.UserRole, t)
                self.chapter_list.addItem(item)
        self._refresh_buttons()

    def auto_chapters(self) -> None:
        path = self._selected_path()
        info = self.media.get(path or '')
        if not info:
            return
        interval = self.auto_interval.value() * 60
        self.chapters[path] = [0.0] + [float(i) for i in range(interval, int(info.duration), interval)]
        self._select_media()

    def add_chapter(self) -> None:
        path = self._selected_path()
        info = self.media.get(path or '')
        if not info:
            return
        text, ok = QInputDialog.getText(self, 'Новая глава', 'Время (ЧЧ:ММ:СС):', text='00:10:00')
        if not ok:
            return
        try:
            sec = parse_timecode(text)
            if sec >= info.duration or sec in self.chapters[path]:
                raise ValueError('Глава уже существует или находится за концом видео')
        except ValueError as exc:
            QMessageBox.warning(self, 'Некорректное время', str(exc))
            return
        self.chapters[path] = sorted([*self.chapters[path], sec])
        self._select_media()

    def remove_chapter(self) -> None:
        path = self._selected_path()
        item = self.chapter_list.currentItem()
        if not path or not item:
            return
        sec = float(item.data(Qt.UserRole))
        if sec == 0:
            QMessageBox.information(self, 'Начало фильма', 'Главу 00:00:00 удалять нельзя.')
            return
        self.chapters[path].remove(sec)
        self._select_media()

    def remove_media(self) -> None:
        row = self.movies.currentRow()
        if row < 0:
            return
        item = self.movies.takeItem(row)
        path = item.data(Qt.UserRole)
        self.media.pop(path, None)
        self.chapters.pop(path, None)
        self._select_media()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        scanning = bool(self.scan_thread and self.scan_thread.isRunning())
        busy = bool(self.build_thread and self.build_thread.isRunning())
        self.build_button.setEnabled(bool(self.media) and not scanning and not busy)
        self.cancel_button.setEnabled(busy)
        self.add_button.setEnabled(not scanning and not busy)
        self.remove_button.setEnabled(not scanning and not busy and self.movies.currentItem() is not None)
        self.statusBar().showMessage(
            f'Файлов: {len(self.media)}  |  Сканирование: {"да" if scanning else "нет"}  |  '
            f'Сборка: {"идёт" if busy else "нет"}')

    def _message(self, value: str) -> None:
        self.log.appendPlainText(value)

    def start_build(self) -> None:
        if not self.media:
            return
        config = self._config()
        self._save_config()
        if not config['output']:
            QMessageBox.warning(self, 'Выходная папка', 'Укажите выходную папку.')
            return
        jobs = []
        for i in range(self.movies.count()):
            path = self.movies.item(i).data(Qt.UserRole)
            if path in self.media:
                jobs.append((self.media[path], list(self.chapters[path])))
        bad = [info.name for info, _ in jobs if info.is_hdr]
        if bad:
            QMessageBox.warning(self, 'HDR пока не поддерживается',
                                'Нельзя создавать обычный BD из HDR без правильного тонмаппинга.\n' + '\n'.join(bad))
            return
        response = QMessageBox.question(self, 'Альфа-версия без меню',
            'Будет создан Blu-ray с главами, но БЕЗ интерактивного меню.\n'
            'Выбор языка и субтитров ещё не реализован.\n\nПродолжить создание тестового образа?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if response != QMessageBox.Yes:
            return
        self.progress.setValue(0)
        self.build_thread = BuildThread(jobs, config, self.profile.currentText(),
                                        self.output_mode.currentIndex() == 0,
                                        self.encoder.currentIndex() == 1)
        self.build_thread.message.connect(self._message)
        self.build_thread.progress_changed.connect(self.progress.setValue)
        self.build_thread.item_started.connect(lambda p: self._message('Начинаем: ' + Path(p).name))
        self.build_thread.item_done.connect(lambda p, dest: self._message('ГОТОВО: ' + dest))
        self.build_thread.failed.connect(lambda p, err: self._message('ОШИБКА ' + Path(p).name + ': ' + err))
        self.build_thread.finished_all.connect(self._build_finished)
        self.build_thread.finished.connect(self._refresh_buttons)
        self.build_thread.start()
        self._refresh_buttons()

    def _build_finished(self, success: bool) -> None:
        self._message('Очередь завершена.' if success else 'Очередь завершилась с ошибками или была отменена.')

    def cancel_build(self) -> None:
        if self.build_thread and self.build_thread.isRunning():
            self._message('Запрошена отмена операции…')
            self.build_thread.cancel()

    def _project_data(self) -> dict:
        return {'format_version': 1, 'title': self.menu_title.text(),
                'files': [self.movies.item(i).data(Qt.UserRole) for i in range(self.movies.count())],
                'chapters': self.chapters, 'profile': self.profile.currentText(),
                'encoder': self.encoder.currentIndex(), 'as_iso': self.output_mode.currentIndex() == 0}

    def save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить проект', 'DiscForge_project.dfr.json',
                                             'DiscForge RU (*.dfr.json)')
        if path:
            Path(path).write_text(json.dumps(self._project_data(), ensure_ascii=False, indent=2), encoding='utf-8')
            self._message('Проект сохранён: ' + path)

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, 'Открыть проект', '', 'DiscForge RU (*.dfr.json)')
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('format_version') != 1 or not isinstance(data.get('files'), list):
                raise ValueError('Неизвестный формат проекта')
            paths = [p for p in data['files'] if isinstance(p, str)]
            raw = data.get('chapters', {})
            if not isinstance(raw, dict):
                raise ValueError('Неверный раздел глав')
            if not self.new_project():
                return
            self.menu_title.setText(str(data.get('title', 'Моя коллекция Blu-ray')))
            if data.get('profile') in CAPACITIES:
                self.profile.setCurrentText(data['profile'])
            self.encoder.setCurrentIndex(1 if data.get('encoder') == 1 else 0)
            self.output_mode.setCurrentIndex(0 if data.get('as_iso', True) else 1)
            for p in paths:
                v = raw.get(p)
                if isinstance(v, list) and v and v[0] == 0 and all(isinstance(x, (int, float)) for x in v):
                    if all(a < b for a, b in zip(v, v[1:])) and all(x >= 0 for x in v):
                        self.chapters[p] = [float(x) for x in v]
            self._queue_scan(paths)
            self._message('Проект открыт: ' + path)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, 'Ошибка проекта', str(exc))

    def new_project(self) -> bool:
        if ((self.build_thread and self.build_thread.isRunning()) or
                (self.scan_thread and self.scan_thread.isRunning())):
            QMessageBox.warning(self, 'Операция выполняется', 'Дождитесь завершения текущей операции.')
            return False
        self.movies.clear()
        self.media.clear()
        self.chapters.clear()
        self.chapter_list.clear()
        self.menu_title.setText('Моя коллекция Blu-ray')
        self._select_media()
        return True

    def about(self) -> None:
        QMessageBox.about(self, 'DiscForge RU',
            f'DiscForge RU {VERSION}\nОткрытый исходный код (MIT).\n\n'
            'Альфа: анализ, очередь, главы, BDMV/ISO.\n'
            'Не реализовано: дисковое меню BD-J/HDMV, UHD-авторинг, запись на привод.')

    def closeEvent(self, event) -> None:
        if (self.build_thread and self.build_thread.isRunning()) or (
                self.scan_thread and self.scan_thread.isRunning()):
            QMessageBox.warning(self, 'Операция выполняется', 'Сначала завершите или отмените текущую операцию.')
            event.ignore()
            return
        self._save_config()
        super().closeEvent(event)


STYLE = '''
QWidget { background: #101724; color: #e3eaf6; font-size: 12px; }
QMainWindow, QTabWidget::pane { background: #101724; }
QLabel#brand { font-size: 26px; font-weight: 800; }
QLabel#tag { color: #95a3bb; font-size: 11px; letter-spacing: 1px; }
QLabel#section { font-size: 16px; font-weight: 700; }
QLabel#warning { background: #302925; border: 1px solid #80623c; color: #ffcf91; border-radius: 7px; padding: 10px; }
QLabel#details { background: #192234; border-radius: 7px; padding: 10px; color: #b9c9e0; }
QLabel#hint { color: #9bacc3; padding: 7px; }
QLineEdit, QListWidget, QPlainTextEdit, QComboBox, QSpinBox { background: #182337; border: 1px solid #34445e; border-radius: 6px; padding: 7px; selection-background-color: #3268b4; }
QGroupBox { border: 1px solid #33435a; border-radius: 9px; margin-top: 13px; padding: 15px 9px 9px 9px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 13px; padding: 0 7px; }
QPushButton { background: #273952; border: 1px solid #3b5573; padding: 8px 13px; border-radius: 6px; }
QPushButton:hover { background: #355170; }
QPushButton:disabled { background: #1b2636; color: #62718a; border-color: #28354a; }
QPushButton#primary { background: #2478db; border-color: #2478db; font-weight: 700; color: #fff; }
QPushButton#primary:hover { background: #3491ff; }
QTabBar::tab { background: #1d2a3d; padding: 10px 16px; border: 1px solid #304259; }
QTabBar::tab:selected { background: #2b527f; }
QProgressBar { background: #1d293b; border: 1px solid #30435a; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: #3287e5; border-radius: 5px; }
QStatusBar { color: #9fb1c9; }
'''


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setFont(QFont('Segoe UI', 10))
    w = Window()
    w.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
