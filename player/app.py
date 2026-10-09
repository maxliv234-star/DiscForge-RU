"""DiscForge Player: Blu-ray viewer using PySide6 and system LibVLC (alpha)."""
import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QFileDialog, QInputDialog, QMenu,
    QMessageBox, QSlider)
from .backend import SourceError, bluray_uri, bdmv_uri, file_uri

class Player(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DiscForge Player RU 0.1 Alpha")
        self.resize(1050, 680)
        self.instance = self.engine = self.vlc = None
        self.dragging = False
        panel = QWidget()
        self.setCentralWidget(panel)
        layout = QVBoxLayout(panel)
        self.screen = QWidget()
        self.screen.setStyleSheet("background: black")
        self.screen.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        tools = QHBoxLayout()
        self.button(tools, "💿 ASUS / диск", self.open_disc)
        self.button(tools, "📁 BDMV", self.open_folder)
        self.button(tools, "🎞 Видео / ISO", self.open_file)
        layout.addLayout(tools)
        layout.addWidget(self.screen, 1)
        self.label = QLabel("Выберите Blu-ray-привод или видео. Цель — Full HD.")
        layout.addWidget(self.label)
        timeline = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderPressed.connect(lambda: setattr(self, "dragging", True))
        self.slider.sliderReleased.connect(self.seek)
        timeline.addWidget(self.slider)
        self.time_label = QLabel("00:00 / 00:00")
        timeline.addWidget(self.time_label)
        layout.addLayout(timeline)
        bar = QHBoxLayout()
        for label, callback in (
            ("▶ / ⏸", self.pause), ("■", self.stop),
            ("⏮", self.previous), ("⏭", self.next),
            ("Звук", self.audio), ("Субтитры", self.subtitles),
            ("Меню", lambda: self.navigate("popup")),
            ("↑", lambda: self.navigate("up")), ("↓", lambda: self.navigate("down")),
            ("←", lambda: self.navigate("left")), ("→", lambda: self.navigate("right")),
            ("OK", lambda: self.navigate("activate")), ("⛶", self.fullscreen)
        ):
            self.button(bar, label, callback)
        layout.addLayout(bar)
        layout.addWidget(QLabel("BD-J-меню требуют LibVLC/libbluray и иногда Java; поддержка зависит от сборки VLC."))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)
        try:
            import vlc
            self.vlc = vlc
            self.instance = vlc.Instance("--no-video-title-show", "--bluray-menu")
            if self.instance is None:
                raise RuntimeError("Не удалось запустить LibVLC")
            self.engine = self.instance.media_player_new()
        except (ImportError, OSError, RuntimeError) as exc:
            self.label.setText("Нужен установленный VLC: " + str(exc))

    def button(self, row, name, callback):
        widget = QPushButton(name)
        widget.clicked.connect(callback)
        row.addWidget(widget)

    def open(self, uri):
        if self.engine is None:
            QMessageBox.warning(self, "VLC", "Установите VLC и python-vlc.")
            return
        try:
            self.engine.stop()
            handle = int(self.screen.winId())
            if sys.platform == "win32":
                self.engine.set_hwnd(handle)
            elif sys.platform == "darwin":
                self.engine.set_nsobject(handle)
            else:
                self.engine.set_xwindow(handle)
            media = self.instance.media_new_location(uri)
            self.engine.set_media(media)
            media.release()
            self.label.setText(uri)
            if self.engine.play() == -1:
                self.label.setText("Ошибка запуска воспроизведения")
        except Exception as exc:
            self.label.setText(str(exc))

    def checked_open(self, prepare, path):
        try:
            self.open(prepare(path))
        except SourceError as exc:
            QMessageBox.warning(self, "Источник", str(exc))

    def open_disc(self):
        default = "D:" if sys.platform == "win32" else "/Volumes/"
        path, ok = QInputDialog.getText(
            self, "Привод Blu-ray", "Буква привода (D:) либо путь к диску:", text=default)
        if ok:
            self.checked_open(bluray_uri, path)

    def open_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Каталог BDMV")
        if path:
            self.checked_open(bdmv_uri, path)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "ISO или видео", "", "Медиа (*.iso *.mkv *.mp4 *.mov *.m2ts *.mts *.ts *.avi)")
        if path:
            self.checked_open(file_uri, path)

    def pause(self):
        if self.engine:
            self.engine.pause() if self.engine.is_playing() else self.engine.play()

    def stop(self):
        if self.engine:
            self.engine.stop()

    def previous(self):
        if self.engine:
            self.engine.previous_chapter()

    def next(self):
        if self.engine:
            self.engine.next_chapter()

    def track_menu(self, get_tracks, select_track):
        try:
            menu = QMenu(self)
            for track_id, name in get_tracks() or []:
                title = name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)
                item = menu.addAction(title)
                item.triggered.connect(lambda checked=False, n=track_id: select_track(n))
            if menu.isEmpty():
                menu.addAction("Нет дорожек").setEnabled(False)
            menu.exec(self.mapToGlobal(self.rect().center()))
        except Exception as exc:
            self.label.setText(str(exc))

    def audio(self):
        if self.engine:
            self.track_menu(self.engine.audio_get_track_description, self.engine.audio_set_track)

    def subtitles(self):
        if self.engine:
            self.track_menu(self.engine.video_get_spu_description, self.engine.video_set_spu)

    def navigate(self, direction):
        if self.engine and self.vlc:
            try:
                mode = getattr(self.vlc.NavigateMode, direction, 5 if direction == "popup" else None)
                if mode is not None:
                    self.engine.navigate(mode)
            except Exception as exc:
                self.label.setText(str(exc))

    def fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def seek(self):
        self.dragging = False
        if self.engine:
            length = self.engine.get_length()
            if length > 0:
                self.engine.set_time(length * self.slider.value() // 1000)

    def tick(self):
        if not self.engine:
            return
        try:
            total, current = self.engine.get_length(), self.engine.get_time()
            if total > 0:
                if not self.dragging:
                    self.slider.setValue(max(0, min(1000, current * 1000 // total)))
                t = lambda ms: f"{max(0, ms // 1000) // 60:02}:{max(0, ms // 1000) % 60:02}"
                self.time_label.setText(t(current) + " / " + t(total))
            if self.vlc and self.engine.get_state() == self.vlc.State.Error:
                self.label.setText("Ошибка чтения: проверьте VLC/libbluray и диск.")
        except Exception:
            pass

    def closeEvent(self, event):
        self.timer.stop()
        if self.engine:
            self.engine.stop()
            self.engine.release()
        if self.instance:
            self.instance.release()
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    window = Player()
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
