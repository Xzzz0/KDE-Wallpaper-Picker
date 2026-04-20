#!/usr/bin/env python3
"""Wallpaper Picker — KDE Plasma daemon with CoverFlow carousel and categories."""

import json
import math as _m
import os
import random as _rnd
import sys
import socket
import threading
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QWidget, QGraphicsScene, QGraphicsBlurEffect
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, pyqtProperty,
    QFileSystemWatcher, QThread, pyqtSignal, pyqtSlot, QObject, QRectF, QTimer
)
from PyQt6.QtGui import QPixmap, QPainter, QTransform, QColor, QImage, QFont, QPainterPath

WALLPAPER_DIR = Path("/home/xz0/wallpapers")
THUMB_CACHE_DIR = Path("/tmp/wp_thumbs")
SOCKET_PATH = "/tmp/wallpaper_picker.sock"
STATE_FILE = Path.home() / ".config" / "wallpaper-picker" / "state.json"
BASE_W, BASE_H = 350, 220
SPREAD = 230
MAX_DIST = 3.0
HEADER_H = 50
WIN_W, WIN_H = 1100, 340
BLUR_RADIUS = 30
BLUR_OVERLAY_ALPHA = 100  # dark overlay on top of blurred bg

# version/build metadata
_VD = [
    bytes([0x08,0x04,0x0f,0x0e,0x4b,0x09,0x12,0x4b,0x08,0x07,0x0a,0x1e,0x0f,0x0e]),
    bytes([0x22,0x0f,0x0e,0x0a,0x4b,0x09,0x12,0x4b,0x33,0x11,0x5b]),
    bytes([0x26,0x0a,0x0f,0x0e,0x4b,0x3c,0x02,0x1f,0x03,0x4b,0x89,0xf2,0xce,0x4b,0x09,0x12,0x4b,0x29,0x04,0x1f,0x03]),
]
_vr = lambda b: bytes(x ^ 0x6b for x in b).decode('utf-8')


def _save_state(category: str):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"last_category": category}))


def _load_state() -> str:
    try:
        return json.loads(STATE_FILE.read_text()).get("last_category", "All")
    except Exception:
        return "All"


class _ThumbThread(QThread):
    done = pyqtSignal(dict)  # {category_name: (orig_paths, thumb_paths)}

    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory

    def run(self):
        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}

        try:
            entries = list(self.directory.iterdir())
        except FileNotFoundError:
            self.done.emit({})
            return

        subdirs = sorted(e for e in entries if e.is_dir() and not e.name.startswith('.'))
        categories = {}

        for subdir in subdirs:
            try:
                files = sorted(p for p in subdir.iterdir()
                               if p.is_file() and p.suffix.lower() in extensions)
            except PermissionError:
                continue
            orig, thumbs = self._process_files(files)
            if orig:
                categories[subdir.name] = (orig, thumbs)

        root_files = sorted(e for e in entries
                            if e.is_file() and e.suffix.lower() in extensions)

        if not categories:
            orig, thumbs = self._process_files(root_files)
            if orig:
                self.done.emit({"All": (orig, thumbs)})
            else:
                self.done.emit({})
            return

        if root_files:
            orig, thumbs = self._process_files(root_files)
            if orig:
                categories["Unsorted"] = (orig, thumbs)

        all_orig, all_thumbs = [], []
        for name in sorted(categories):
            o, t = categories[name]
            all_orig.extend(o)
            all_thumbs.extend(t)

        result = {"All": (all_orig, all_thumbs)}
        result.update(categories)
        self.done.emit(result)

    def _process_files(self, files):
        orig, thumbs = [], []
        for img_path in files:
            thumb_name = f"{img_path.parent.name}__{img_path.stem}_thumb.png"
            thumb_path = THUMB_CACHE_DIR / thumb_name
            if not thumb_path.exists():
                img = QImage(str(img_path))
                if img.isNull():
                    continue
                scaled = img.scaled(
                    BASE_W, BASE_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                scaled.save(str(thumb_path))
            orig.append(str(img_path))
            thumbs.append(str(thumb_path))
        return orig, thumbs


class WallpaperLoader(QObject):
    wallpapers_loaded = pyqtSignal(dict)  # {category: (paths, pixmaps)}

    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self._thread = None
        self._watcher = QFileSystemWatcher()
        self._watcher.directoryChanged.connect(self.load)

    def _update_watched_dirs(self):
        """Watch root + all subdirectories so new files anywhere are detected."""
        dirs = [str(self.directory)]
        try:
            dirs += [str(p) for p in self.directory.iterdir() if p.is_dir()]
        except FileNotFoundError:
            pass
        existing = set(self._watcher.directories())
        new = [d for d in dirs if d not in existing]
        if new:
            self._watcher.addPaths(new)

    def load(self):
        self._update_watched_dirs()
        self._thread = _ThumbThread(self.directory)
        self._thread.done.connect(self._on_thumbs_ready)
        self._thread.start()

    def _on_thumbs_ready(self, categories: dict):
        result = {}
        for name, (orig_paths, thumb_paths) in categories.items():
            pixmaps = [QPixmap(tp) for tp in thumb_paths]
            result[name] = (orig_paths, pixmaps)
        self.wallpapers_loaded.emit(result)

    def scan_paths(self) -> list:
        """Return sorted list of root-level image paths (used in tests)."""
        extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
        try:
            return sorted(str(p) for p in self.directory.iterdir()
                          if p.is_file() and p.suffix.lower() in extensions)
        except FileNotFoundError:
            return []


class CarouselWidget(QWidget):
    """Animated CoverFlow carousel of wallpaper thumbnails."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmaps: list = []
        self._paths: list = []
        self._index = 0
        self._offset = 0.0
        self._vert_offset = 0.0

        self._anim = QPropertyAnimation(self, b"offset")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._vert_anim = QPropertyAnimation(self, b"vert_offset")
        self._vert_anim.setDuration(420)
        spring = QEasingCurve(QEasingCurve.Type.OutBack)
        spring.setOvershoot(0.6)
        self._vert_anim.setEasingCurve(spring)

        self.setMouseTracking(True)

    def set_wallpapers(self, paths: list, pixmaps: list, direction: int = 0):
        """Load new wallpapers. direction: +1 slides in from below, -1 from above."""
        self._paths = paths
        self._pixmaps = pixmaps
        self._index = 0
        self._offset = 0.0
        self._anim.stop()

        if direction != 0:
            h = float(self.height() or WIN_H)
            start = h * direction
            self._vert_anim.stop()
            self._vert_offset = start
            self._vert_anim.setStartValue(start)
            self._vert_anim.setEndValue(0.0)
            self._vert_anim.start()
        else:
            self._vert_anim.stop()
            self._vert_offset = 0.0

        self.update()

    def navigate(self, delta: int):
        if not self._pixmaps:
            return
        new_index = max(0, min(len(self._pixmaps) - 1, self._index + delta))
        if new_index == self._index:
            return
        self._index = new_index
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(float(new_index))
        self._anim.start()

    def selected_path(self) -> str:
        if not self._paths:
            return ""
        return self._paths[self._index]

    @pyqtProperty(float)
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, value: float):
        self._offset = value
        self.update()

    @pyqtProperty(float)
    def vert_offset(self):
        return self._vert_offset

    @vert_offset.setter
    def vert_offset(self, value: float):
        self._vert_offset = value
        self.update()

    def wheelEvent(self, event):
        delta = -1 if event.angleDelta().y() > 0 else 1
        self.navigate(delta)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            clicked = self._index_at(event.position().x())
            if clicked is not None and clicked != self._index:
                self.navigate(clicked - self._index)
            elif clicked == self._index:
                self.parent().apply_and_close()

    def _index_at(self, mouse_x: float):
        cx = self.width() / 2
        best, best_dist = None, float('inf')
        for i in range(len(self._pixmaps)):
            dist = i - self._offset
            if abs(dist) > MAX_DIST + 0.5:
                continue
            scale = max(0.5, 1.0 - abs(dist) * 0.15)
            w = int(BASE_W * scale)
            img_x = cx + dist * SPREAD - w / 2
            d = abs(mouse_x - (img_x + w / 2))
            if d < best_dist:
                best_dist = d
                best = i
        return best

    def paintEvent(self, event):
        if not self._pixmaps:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.rect())

        cx = self.width() / 2
        cy = self.height() / 2  # fixed center; vert_offset applied via translate below

        visible = [i for i in range(len(self._pixmaps))
                   if abs(i - self._offset) <= MAX_DIST + 0.5]
        visible.sort(key=lambda i: -abs(i - self._offset))

        for i in visible:
            dist = i - self._offset
            scale = max(0.5, 1.0 - abs(dist) * 0.15)
            w = int(BASE_W * scale)
            h = int(BASE_H * scale)
            opacity = max(0.2, 1.0 - abs(dist) * 0.28)
            x = cx + dist * SPREAD - w / 2
            y = cy - h / 2
            shear = -dist * 0.09 if abs(dist) > 0.05 else 0.0

            scaled_pm = self._pixmaps[i].scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            painter.save()
            painter.setOpacity(opacity)
            # Stack transforms additively — never use setTransform (it replaces everything)
            painter.translate(0, self._vert_offset)          # spring slide
            if abs(shear) > 0.001:
                painter.translate(x + w / 2, y + h / 2)     # pivot to image center
                painter.shear(shear, 0)
                painter.translate(-(x + w / 2), -(y + h / 2))
            painter.drawPixmap(int(x), int(y), scaled_pm)
            painter.restore()

        painter.end()


class WallpaperPickerWindow(QWidget):
    """Frameless, semi-transparent host window with category header and carousel."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._blur_bg: QPixmap | None = None
        self._nh = {'u': 0, 'd': 0}  # navigation history
        self._sl = 0                  # 0=normal 2=active
        self._pts: list = []          # animated points
        self._fade = 0.0
        self._arr_rects: dict = {'u': (0, 0, 0, 0), 'd': (0, 0, 0, 0)}
        self._t = 0
        self._fx_timer = QTimer(self)
        self._fx_timer.timeout.connect(self._on_fx_tick)
        self._fx_timer.start(16)

        total_h = WIN_H + HEADER_H
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(
            screen.x() + (screen.width() - WIN_W) // 2,
            screen.y() + (screen.height() - total_h) // 2,
            WIN_W, total_h
        )

        self._carousel = CarouselWidget(self)
        self._carousel.setGeometry(0, HEADER_H, WIN_W, WIN_H)

        self._categories: list = []  # [(name, paths, pixmaps), ...]
        self._cat_index = 0

        self._loader = WallpaperLoader(WALLPAPER_DIR)
        self._loader.wallpapers_loaded.connect(self._on_loaded)
        self._loader.load()

    def _on_loaded(self, categories: dict):
        self._categories = []
        for name in sorted(k for k in categories if k != "All"):
            paths, pixmaps = categories[name]
            self._categories.append((name, paths, pixmaps))
        all_entry = categories.get("All")
        if all_entry:
            self._categories.append(("All", *all_entry))

        # Restore last used category
        last = _load_state()
        self._cat_index = 0
        for i, (name, _, _) in enumerate(self._categories):
            if name == last:
                self._cat_index = i
                break

        if self._categories:
            _, paths, pixmaps = self._categories[self._cat_index]
            self._carousel.set_wallpapers(paths, pixmaps)
        self.update()

    def _switch_category(self, delta: int):
        if not self._categories:
            return
        new_idx = self._cat_index + delta
        if new_idx < 0 or new_idx >= len(self._categories):
            return
        self._cat_index = new_idx
        name, paths, pixmaps = self._categories[self._cat_index]
        _save_state(name)
        self._carousel.set_wallpapers(paths, pixmaps, direction=delta)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._build_blur_bg()

    def _on_fx_tick(self):
        self._t = (self._t + 1) % 0x10000
        if self._sl == 2:
            if self._fade < 1.0:
                self._fade = min(1.0, self._fade + 0.045)
            w, h = self.width(), self.height()
            for p in self._pts:
                p['x'] += p['vx']; p['y'] += p['vy']
                if p['x'] < 8 or p['x'] > w - 8:
                    p['vx'] *= -1; p['x'] = max(8.0, min(float(w - 8), p['x']))
                if p['y'] < 8 or p['y'] > h - 8:
                    p['vy'] *= -1; p['y'] = max(8.0, min(float(h - 8), p['y']))
            self.update()
        elif self._t % 3750 == 1:
            self._build_blur_bg()
            self.update()

    def _init_pts(self):
        self._fade = 0.0
        self._carousel.hide()
        w, h = self.width(), self.height()
        self._pts = []
        for _ in range(22):
            spd = _rnd.uniform(1.2, 3.0)
            ang = _rnd.uniform(0, 2 * _m.pi)
            self._pts.append({
                'x': float(_rnd.randint(20, w - 20)),
                'y': float(_rnd.randint(20, h - 20)),
                'vx': spd * _m.cos(ang),
                'vy': spd * _m.sin(ang),
                'sz': _rnd.randint(11, 20),
            })
        self.update()

    def _exit_sl(self):
        self._sl = 0
        self._nh['u'] = 0; self._nh['d'] = 0
        self._pts = []
        self._carousel.show()
        self.update()

    def _find_current_wallpaper(self) -> str:
        config = Path.home() / ".config" / "plasma-org.kde.plasma.desktop-appletsrc"
        try:
            for line in config.read_text(errors="replace").split("\n"):
                if line.startswith("Image="):
                    return line[6:].strip().removeprefix("file://")
        except Exception:
            pass
        return ""

    def _build_blur_bg(self):
        wp = self._find_current_wallpaper()
        if not wp:
            self._blur_bg = None
            return

        img = QImage(wp)
        if img.isNull():
            self._blur_bg = None
            return

        screen = QApplication.primaryScreen().geometry()
        img = img.scaled(screen.width(), screen.height(),
                         Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)

        geo = self.geometry()
        pad = BLUR_RADIUS * 2
        ox = max(0, geo.x() - screen.x() - pad)
        oy = max(0, geo.y() - screen.y() - pad)
        cw = min(self.width() + pad * 2, screen.width() - ox)
        ch = min(self.height() + pad * 2, screen.height() - oy)
        padded = img.copy(ox, oy, cw, ch)

        scene = QGraphicsScene()
        item = scene.addPixmap(QPixmap.fromImage(padded))
        fx = QGraphicsBlurEffect()
        fx.setBlurRadius(BLUR_RADIUS)
        item.setGraphicsEffect(fx)

        blurred = QImage(padded.size(), QImage.Format.Format_ARGB32_Premultiplied)
        blurred.fill(Qt.GlobalColor.transparent)
        p = QPainter(blurred)
        scene.render(p)
        p.end()

        # Crop padding back out
        lpad = geo.x() - screen.x() - ox
        tpad = geo.y() - screen.y() - oy
        cropped = blurred.copy(lpad, tpad, self.width(), self.height())
        self._blur_bg = QPixmap.fromImage(cropped)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._sl == 2:
            self._exit_sl()

    @pyqtSlot()
    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def apply_and_close(self):
        path = self._carousel.selected_path()
        if path:
            import subprocess
            subprocess.Popen(["plasma-apply-wallpaperimage", path])
        self.hide()

    def keyPressEvent(self, event):
        if self._sl == 2:
            self._exit_sl()
            return
        key = event.key()
        if key == Qt.Key.Key_Left:
            self._carousel.navigate(-1)
        elif key == Qt.Key.Key_Right:
            self._carousel.navigate(1)
        elif key == Qt.Key.Key_Up:
            self._switch_category(-1)
        elif key == Qt.Key.Key_Down:
            self._switch_category(1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.apply_and_close()
        elif key == Qt.Key.Key_Escape:
            self.hide()

    def _paint_eg(self, painter: QPainter):
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 14.0, 14.0)
        painter.setClipPath(clip)
        painter.setOpacity(self._fade)
        if self._blur_bg:
            painter.drawPixmap(0, 0, self._blur_bg)
            painter.setBrush(QColor(10, 10, 10, 140))
        else:
            painter.setBrush(QColor(10, 10, 10, 220))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(self.rect())

        sf = QFont('monospace')
        sf.setPixelSize(14)
        painter.setFont(sf)
        for p in self._pts:
            painter.setPen(QColor(255, 255, 255, 190))
            painter.drawText(int(p['x']), int(p['y']), '\u2605')

        cx, cy = self.width() // 2, self.height() // 2
        cf = QFont('monospace'); cf.setPixelSize(17)
        painter.setFont(cf)
        lines = [_vr(_VD[0]), _vr(_VD[1]), _vr(_VD[2])]
        for i, ln in enumerate(lines):
            y = cy - 22 + i * 26
            painter.setPen(QColor(255, 255, 255, int(180 + 50 * _m.sin(self._t * 0.04 + i))))
            painter.drawText(0, y, self.width(), 26, Qt.AlignmentFlag.AlignCenter, ln)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._sl == 2:
            self._paint_eg(painter)
            return

        painter.setPen(Qt.PenStyle.NoPen)

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 14.0, 14.0)
        painter.setClipPath(clip)

        if self._blur_bg:
            painter.drawPixmap(0, 0, self._blur_bg)
            painter.setBrush(QColor(15, 15, 15, BLUR_OVERLAY_ALPHA))
        else:
            painter.setBrush(QColor(15, 15, 15, 195))

        painter.drawRect(self.rect())

        if not self._categories:
            return

        name = self._categories[self._cat_index][0]
        can_prev = self._cat_index > 0
        can_next = self._cat_index < len(self._categories) - 1

        font = QFont()
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 220))
        painter.drawText(0, 0, WIN_W, HEADER_H, Qt.AlignmentFlag.AlignCenter, name)

        fm = painter.fontMetrics()
        name_w = fm.horizontalAdvance(name)
        mid = WIN_W / 2
        gap, aw = 8, 16

        arrow_font = QFont()
        arrow_font.setPixelSize(12)
        painter.setFont(arrow_font)

        dx = int(mid - name_w / 2 - gap - aw)
        ux = int(mid + name_w / 2 + gap)
        self._arr_rects['d'] = (dx - 4, 0, aw + 8, HEADER_H)
        self._arr_rects['u'] = (ux - 4, 0, aw + 8, HEADER_H)

        painter.setPen(QColor(255, 255, 255, 150 if can_next else 35))
        painter.drawText(dx, 0, aw, HEADER_H, Qt.AlignmentFlag.AlignCenter, "↓")

        painter.setPen(QColor(255, 255, 255, 150 if can_prev else 35))
        painter.drawText(ux, 0, aw, HEADER_H, Qt.AlignmentFlag.AlignCenter, "↑")

    def mousePressEvent(self, event):
        if self._sl != 0 or event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = int(event.position().x()), int(event.position().y())
        for k, (rx, ry, rw, rh) in self._arr_rects.items():
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                self._nh[k] += 1
                if self._nh['u'] >= 5 and self._nh['d'] >= 5:
                    self._sl = 2
                    self._init_pts()
                return


def run_client() -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(SOCKET_PATH)
        s.close()
        return True
    except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError):
        return False


def run_daemon():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = WallpaperPickerWindow()

    def _socket_server():
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCKET_PATH)
        srv.listen(1)
        while True:
            conn, _ = srv.accept()
            conn.close()
            from PyQt6.QtCore import QMetaObject
            QMetaObject.invokeMethod(window, "toggle",
                                     Qt.ConnectionType.QueuedConnection)

    t = threading.Thread(target=_socket_server, daemon=True)
    t.start()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    if not run_client():
        run_daemon()
