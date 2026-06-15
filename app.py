"""PlayStation Game Recommender - PyQt6 desktop app.

Search a game you like → see its details → get recommendations → share or retry.

Backed by the Supabase `public.games` table (3,840 PS4/PS5 games from IGDB)
and the `search_games()` / `get_recommendations()` Postgres RPC functions.

Run: python app.py
Or set env vars to override the embedded config:
    SUPABASE_URL, SUPABASE_ANON_KEY
"""

from __future__ import annotations

import os
import sys
import textwrap
import webbrowser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

import requests
from PyQt6.QtCore import (
    QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import (
    QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPainter, QPalette,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)
from supabase import Client, create_client


# ---------- Config ----------------------------------------------------------

# Supabase project URL (public, non-sensitive).
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")

# Anon / publishable key. Safe to embed in a client (RLS gates access),
# but we leave it as an env var here so it isn't checked into the repo.
# Set SUPABASE_ANON_KEY in your environment, or create a .env file
# (see .env.example).
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    sys.stderr.write(
        "ERROR: set SUPABASE_URL and SUPABASE_ANON_KEY in your environment.\n"
        "See .env.example for the expected values.\n"
    )
    sys.exit(2)

COVER_BIG = "cover_big"      # 264x374
COVER_SMALL = "cover_small"  # 90x128
IGDB_IMG = "https://images.igdb.com/igdb/image/upload/t_{size}/{image_id}.jpg"

WINDOW_W, WINDOW_H = 1180, 760

# ---------- Theme -----------------------------------------------------------

QSS = """
QMainWindow, QWidget#root {
    background: qlineargradient(x1:0 y1:0 x2:1 y2:1,
        stop:0 #0a0e1a, stop:0.5 #14223e, stop:1 #0a0e1a);
}

QLabel { color: #e6ebff; }
QLabel#title { font-size: 48px; font-weight: 700; letter-spacing: -1px; color: #ffffff; }
QLabel#subtitle { font-size: 16px; color: #8fa3c7; }
QLabel#h2 { font-size: 26px; font-weight: 700; color: #ffffff; }
QLabel#meta { font-size: 14px; color: #8fa3c7; }
QLabel#rating { font-size: 36px; font-weight: 800; color: #ffd23f; }
QLabel#ratingLabel { font-size: 11px; color: #8fa3c7; letter-spacing: 1px; }
QLabel#chip {
    background: rgba(0,114,206,0.18);
    border: 1px solid rgba(0,114,206,0.45);
    border-radius: 10px;
    padding: 4px 10px;
    color: #b8d0f0;
    font-size: 11px;
}
QLabel#summary { font-size: 14px; color: #c8d4ee; line-height: 1.5; }
QLabel#cardName { font-size: 13px; font-weight: 600; color: #ffffff; }
QLabel#cardMeta { font-size: 11px; color: #8fa3c7; }
QLabel#toast {
    background: rgba(0,180,90,0.9); color: white; padding: 10px 18px;
    border-radius: 8px; font-weight: 600;
}

QLineEdit#search {
    background: rgba(255,255,255,0.06);
    border: 2px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    padding: 14px 18px;
    color: white;
    font-size: 16px;
    selection-background-color: #0072ce;
}
QLineEdit#search:focus { border-color: #0072ce; background: rgba(0,114,206,0.08); }

QPushButton {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 10px;
    padding: 10px 22px;
    color: white;
    font-size: 14px;
    font-weight: 600;
}
QPushButton:hover { background: rgba(255,255,255,0.14); border-color: rgba(255,255,255,0.32); }
QPushButton:pressed { background: rgba(255,255,255,0.04); }

QPushButton#primary {
    background: qlineargradient(x1:0 y1:0 x2:1 y2:0, stop:0 #0072ce, stop:1 #00a8e8);
    border: none;
    padding: 12px 28px;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0 y1:0 x2:1 y2:0, stop:0 #008ae0, stop:1 #1bb6f3);
}
QPushButton#ghost { background: transparent; border: 1px solid rgba(255,255,255,0.25); }

QFrame#card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
}
QFrame#card:hover { background: rgba(255,255,255,0.08); border-color: rgba(0,168,232,0.5); }

QListWidget {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
    color: white;
    padding: 6px;
}
QListWidget::item { padding: 10px 12px; border-radius: 6px; }
QListWidget::item:hover { background: rgba(255,255,255,0.06); }
QListWidget::item:selected { background: rgba(0,114,206,0.5); }

QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.2); border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


# ---------- Data ------------------------------------------------------------

@dataclass
class Game:
    id: int
    name: str
    release_year: Optional[int]
    total_rating: Optional[float]
    cover_id: Optional[str]
    summary: Optional[str] = None
    genres: Optional[list] = None
    themes: Optional[list] = None
    developers: Optional[list] = None
    publishers: Optional[list] = None

    @classmethod
    def from_row(cls, row: dict) -> "Game":
        return cls(
            id=row["id"],
            name=row.get("name") or "(untitled)",
            release_year=row.get("release_year"),
            total_rating=row.get("total_rating"),
            cover_id=row.get("cover_id"),
            summary=row.get("summary"),
            genres=row.get("genres") or [],
            themes=row.get("themes") or [],
            developers=row.get("developers") or [],
            publishers=row.get("publishers") or [],
        )


class Backend:
    def __init__(self, url: str, key: str):
        self.sb: Client = create_client(url, key)

    def search(self, q: str, limit: int = 12) -> list[Game]:
        r = self.sb.rpc("search_games", {"q": q, "lim": limit}).execute()
        return [Game.from_row(row) for row in (r.data or [])]

    def details(self, game_id: int) -> Optional[Game]:
        r = (
            self.sb.table("games")
            .select("id,name,release_year,total_rating,cover_id,summary,genres,themes,developers,publishers")
            .eq("id", game_id)
            .limit(1)
            .execute()
        )
        return Game.from_row(r.data[0]) if r.data else None

    def recommend(self, source_id: int, limit: int = 9) -> list[Game]:
        r = self.sb.rpc("get_recommendations", {"source_id": source_id, "lim": limit}).execute()
        return [Game.from_row(row) for row in (r.data or [])]


# ---------- Async image loading --------------------------------------------

class ImageSignals(QObject):
    done = pyqtSignal(str, bytes)
    failed = pyqtSignal(str, str)


class ImageWorker(QRunnable):
    def __init__(self, key: str, url: str, signals: ImageSignals):
        super().__init__()
        self.key, self.url, self.signals = key, url, signals

    @pyqtSlot()
    def run(self) -> None:
        try:
            r = requests.get(self.url, timeout=15)
            r.raise_for_status()
            self.signals.done.emit(self.key, r.content)
        except Exception as e:
            self.signals.failed.emit(self.key, str(e))


class ImageCache(QObject):
    """Async fetcher keyed by (cover_id, size). Caches QPixmaps in memory."""
    loaded = pyqtSignal(str, QPixmap)  # key, pixmap

    def __init__(self) -> None:
        super().__init__()
        self.pool = QThreadPool.globalInstance()
        self.cache: dict[str, QPixmap] = {}
        self.inflight: set[str] = set()
        self.signals = ImageSignals()
        self.signals.done.connect(self._on_done)
        self.signals.failed.connect(self._on_failed)

    def get(self, cover_id: str, size: str = COVER_BIG) -> Optional[QPixmap]:
        return self.cache.get(self._key(cover_id, size))

    def request(self, cover_id: str, size: str = COVER_BIG) -> None:
        if not cover_id:
            return
        key = self._key(cover_id, size)
        if key in self.cache or key in self.inflight:
            if key in self.cache:
                self.loaded.emit(key, self.cache[key])
            return
        self.inflight.add(key)
        url = IGDB_IMG.format(size=size, image_id=cover_id)
        self.pool.start(ImageWorker(key, url, self.signals))

    def _key(self, cover_id: str, size: str) -> str:
        return f"{size}:{cover_id}"

    @pyqtSlot(str, bytes)
    def _on_done(self, key: str, data: bytes) -> None:
        pix = QPixmap()
        if pix.loadFromData(data):
            self.cache[key] = pix
            self.loaded.emit(key, pix)
        self.inflight.discard(key)

    @pyqtSlot(str, str)
    def _on_failed(self, key: str, _err: str) -> None:
        self.inflight.discard(key)


def placeholder_pixmap(w: int, h: int, label: str = "?") -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(QColor(20, 28, 50))
    p = QPainter(pix)
    p.setPen(QColor(120, 140, 180))
    f = QFont()
    f.setPointSize(28)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    return pix


# ---------- Shared widgets --------------------------------------------------

def chip(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("chip")
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
    return lbl


class CoverLabel(QLabel):
    def __init__(self, w: int, h: int):
        super().__init__()
        self.target_w, self.target_h = w, h
        self.setFixedSize(w, h)
        self.setPixmap(placeholder_pixmap(w, h))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_cover(self, pix: QPixmap) -> None:
        self.setPixmap(pix.scaled(
            self.target_w, self.target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))


# ---------- Home screen -----------------------------------------------------

class HomeScreen(QWidget):
    game_chosen = pyqtSignal(int)  # game id

    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend

        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 80, 80, 80)
        layout.setSpacing(18)
        layout.addStretch(2)

        title = QLabel("PlayStation Game Recommender")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Tell us a game you loved - we'll find more like it.")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search for a game…  (e.g. Elden Ring, God of War, Hades)")
        self.search.setFixedWidth(560)
        self.search.returnPressed.connect(self._on_search)

        go_btn = QPushButton("Search")
        go_btn.setObjectName("primary")
        go_btn.setFixedWidth(140)
        go_btn.clicked.connect(self._on_search)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.search)
        row.addWidget(go_btn)
        row.addStretch()

        self.results = QListWidget()
        self.results.setFixedWidth(720)
        self.results.setMaximumHeight(280)
        self.results.itemActivated.connect(self._on_pick)
        self.results.hide()

        results_row = QHBoxLayout()
        results_row.addStretch()
        results_row.addWidget(self.results)
        results_row.addStretch()

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(20)
        layout.addLayout(row)
        layout.addLayout(results_row)
        layout.addStretch(3)

    def reset(self) -> None:
        self.search.clear()
        self.results.clear()
        self.results.hide()
        self.search.setFocus()

    def _on_search(self) -> None:
        q = self.search.text().strip()
        if len(q) < 2:
            return
        try:
            matches = self.backend.search(q, 12)
        except Exception as e:
            QMessageBox.warning(self, "Search failed", f"Couldn't reach Supabase:\n{e}")
            return
        if not matches:
            self.results.clear()
            self.results.addItem(QListWidgetItem(f"No games found for “{q}”."))
            self.results.show()
            return
        if len(matches) == 1:
            self.game_chosen.emit(matches[0].id)
            return
        self.results.clear()
        for g in matches:
            year = f" ({g.release_year})" if g.release_year else ""
            rating = f"  ★ {g.total_rating:.0f}" if g.total_rating else ""
            item = QListWidgetItem(f"{g.name}{year}{rating}")
            item.setData(Qt.ItemDataRole.UserRole, g.id)
            self.results.addItem(item)
        self.results.show()

    def _on_pick(self, item: QListWidgetItem) -> None:
        gid = item.data(Qt.ItemDataRole.UserRole)
        if gid is not None:
            self.game_chosen.emit(int(gid))


# ---------- Detail screen ---------------------------------------------------

class DetailScreen(QWidget):
    back_pressed = pyqtSignal()
    next_pressed = pyqtSignal(int)  # game id

    def __init__(self, images: ImageCache):
        super().__init__()
        self.images = images
        self.current: Optional[Game] = None
        self._cover_key: Optional[str] = None
        images.loaded.connect(self._on_image_loaded)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(60, 36, 60, 36)
        outer.setSpacing(20)

        top = QHBoxLayout()
        back = QPushButton("← Back")
        back.setObjectName("ghost")
        back.setFixedWidth(110)
        back.clicked.connect(self.back_pressed.emit)
        top.addWidget(back)
        top.addStretch()
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(40)

        self.cover = CoverLabel(264, 374)
        body.addWidget(self.cover, alignment=Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(10)

        self.title = QLabel(" ")
        self.title.setObjectName("h2")
        self.title.setWordWrap(True)
        right.addWidget(self.title)

        self.meta = QLabel(" ")
        self.meta.setObjectName("meta")
        right.addWidget(self.meta)

        rating_row = QHBoxLayout()
        rating_row.setSpacing(8)
        rating_row.setContentsMargins(0, 10, 0, 6)
        self.rating = QLabel("-")
        self.rating.setObjectName("rating")
        rlabel = QLabel("RATING / 100")
        rlabel.setObjectName("ratingLabel")
        rating_row.addWidget(self.rating)
        rating_row.addWidget(rlabel, alignment=Qt.AlignmentFlag.AlignBottom)
        rating_row.addStretch()
        right.addLayout(rating_row)

        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(6)
        self.chips_row.setContentsMargins(0, 0, 0, 6)
        self.chips_row.addStretch()
        chips_holder = QWidget()
        chips_holder.setLayout(self.chips_row)
        right.addWidget(chips_holder)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.summary = QLabel("")
        self.summary.setObjectName("summary")
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.summary)
        scroll.setMinimumHeight(180)
        right.addWidget(scroll, 1)

        nxt = QPushButton("See recommendations  →")
        nxt.setObjectName("primary")
        nxt.setFixedWidth(280)
        nxt.clicked.connect(self._emit_next)
        right.addWidget(nxt, alignment=Qt.AlignmentFlag.AlignRight)

        body.addLayout(right, 1)
        outer.addLayout(body, 1)

    def show_game(self, game: Game) -> None:
        self.current = game
        self.title.setText(game.name)

        bits = []
        if game.release_year:
            bits.append(str(game.release_year))
        if game.developers:
            bits.append("·  " + ", ".join(game.developers[:2]))
        self.meta.setText("  ".join(bits))

        self.rating.setText(f"{game.total_rating:.0f}" if game.total_rating else "-")

        # Reset chips
        while self.chips_row.count() > 1:
            it = self.chips_row.takeAt(0)
            if it and it.widget():
                it.widget().deleteLater()
        tags = (game.genres or [])[:3] + (game.themes or [])[:2]
        for t in tags:
            self.chips_row.insertWidget(self.chips_row.count() - 1, chip(t))

        summary = game.summary or "No summary available."
        self.summary.setText(summary)

        self.cover.setPixmap(placeholder_pixmap(264, 374, game.name[:1].upper()))
        if game.cover_id:
            self._cover_key = f"{COVER_BIG}:{game.cover_id}"
            cached = self.images.get(game.cover_id, COVER_BIG)
            if cached is not None:
                self.cover.set_cover(cached)
            else:
                self.images.request(game.cover_id, COVER_BIG)
        else:
            self._cover_key = None

    def _emit_next(self) -> None:
        if self.current:
            self.next_pressed.emit(self.current.id)

    @pyqtSlot(str, QPixmap)
    def _on_image_loaded(self, key: str, pix: QPixmap) -> None:
        if key == self._cover_key:
            self.cover.set_cover(pix)


# ---------- Recommendation card ---------------------------------------------

class GameCard(QFrame):
    clicked = pyqtSignal(int)

    def __init__(self, game: Game, images: ImageCache):
        super().__init__()
        self.setObjectName("card")
        self.game = game
        self.images = images
        self._key = f"{COVER_BIG}:{game.cover_id}" if game.cover_id else None
        images.loaded.connect(self._on_image_loaded)

        self.setFixedSize(180, 320)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 12)
        v.setSpacing(8)

        self.cover = CoverLabel(160, 226)
        v.addWidget(self.cover, alignment=Qt.AlignmentFlag.AlignHCenter)

        name = QLabel(game.name)
        name.setObjectName("cardName")
        name.setWordWrap(True)
        name.setMaximumHeight(40)
        v.addWidget(name)

        meta_bits = []
        if game.release_year:
            meta_bits.append(str(game.release_year))
        if game.total_rating:
            meta_bits.append(f"★ {game.total_rating:.0f}")
        if game.genres:
            meta_bits.append(game.genres[0])
        meta = QLabel("  ·  ".join(meta_bits))
        meta.setObjectName("cardMeta")
        v.addWidget(meta)
        v.addStretch()

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if game.cover_id:
            cached = images.get(game.cover_id, COVER_BIG)
            if cached is not None:
                self.cover.set_cover(cached)
            else:
                images.request(game.cover_id, COVER_BIG)
        else:
            self.cover.setPixmap(placeholder_pixmap(160, 226, game.name[:1].upper()))

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.game.id)
        super().mouseReleaseEvent(ev)

    @pyqtSlot(str, QPixmap)
    def _on_image_loaded(self, key: str, pix: QPixmap) -> None:
        if key == self._key:
            self.cover.set_cover(pix)


# ---------- Recommendations screen ------------------------------------------

class RecommendationsScreen(QWidget):
    back_pressed = pyqtSignal()
    retry_pressed = pyqtSignal()
    card_clicked = pyqtSignal(int)

    def __init__(self, images: ImageCache):
        super().__init__()
        self.images = images
        self.source: Optional[Game] = None
        self.recommendations: list[Game] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.setSpacing(14)

        # Header
        top = QHBoxLayout()
        back = QPushButton("← Back")
        back.setObjectName("ghost")
        back.setFixedWidth(110)
        back.clicked.connect(self.back_pressed.emit)
        top.addWidget(back)

        self.heading = QLabel("Because you like …")
        self.heading.setObjectName("h2")
        top.addStretch()
        top.addWidget(self.heading)
        top.addStretch()

        self.share_btn = QPushButton("Share")
        self.share_btn.clicked.connect(self._share)
        retry = QPushButton("Retry")
        retry.setObjectName("primary")
        retry.clicked.connect(self.retry_pressed.emit)
        top.addWidget(self.share_btn)
        top.addWidget(retry)
        outer.addLayout(top)

        # Grid
        self.grid_holder = QWidget()
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setSpacing(16)
        self.grid.setContentsMargins(0, 10, 0, 10)
        scroll = QScrollArea()
        scroll.setWidget(self.grid_holder)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        # Toast (hidden by default)
        self.toast = QLabel("Copied to clipboard!", self)
        self.toast.setObjectName("toast")
        self.toast.hide()

    def show_for(self, source: Game, recs: list[Game]) -> None:
        self.source = source
        self.recommendations = recs
        self.heading.setText(f"Because you like “{source.name}”")

        # Clear grid
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it and it.widget():
                it.widget().deleteLater()

        cols = 3
        for i, g in enumerate(recs):
            card = GameCard(g, self.images)
            card.clicked.connect(self.card_clicked.emit)
            self.grid.addWidget(card, i // cols, i % cols)

    def _share(self) -> None:
        if not self.source:
            return
        lines = [f"Because I love {self.source.name}, you might enjoy:"]
        for i, g in enumerate(self.recommendations, 1):
            year = f" ({g.release_year})" if g.release_year else ""
            rating = f" - ★ {g.total_rating:.0f}/100" if g.total_rating else ""
            lines.append(f"  {i}. {g.name}{year}{rating}")
        lines.append("\nGenerated by PlayStation Game Recommender")
        text = "\n".join(lines)

        clip = QGuiApplication.clipboard()
        clip.setText(text)
        self._flash_toast("Copied to clipboard!")

    def _flash_toast(self, msg: str) -> None:
        self.toast.setText(msg)
        self.toast.adjustSize()
        # Position bottom-center
        x = (self.width() - self.toast.width()) // 2
        y = self.height() - self.toast.height() - 30
        self.toast.move(x, y)
        self.toast.show()
        QTimer.singleShot(1800, self.toast.hide)


# ---------- Main window -----------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PlayStation Game Recommender")
        self.resize(WINDOW_W, WINDOW_H)
        self.setMinimumSize(960, 640)

        try:
            self.backend = Backend(SUPABASE_URL, SUPABASE_ANON_KEY)
        except Exception as e:
            QMessageBox.critical(self, "Startup failed", f"Couldn't init Supabase client:\n{e}")
            raise

        self.images = ImageCache()

        root = QWidget()
        root.setObjectName("root")
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.home = HomeScreen(self.backend)
        self.detail = DetailScreen(self.images)
        self.recs = RecommendationsScreen(self.images)
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.detail)
        self.stack.addWidget(self.recs)
        v.addWidget(self.stack)

        self.setCentralWidget(root)

        self.home.game_chosen.connect(self._open_detail)
        self.detail.back_pressed.connect(self._go_home)
        self.detail.next_pressed.connect(self._open_recs)
        self.recs.back_pressed.connect(lambda: self.stack.setCurrentWidget(self.detail))
        self.recs.retry_pressed.connect(self._go_home)
        self.recs.card_clicked.connect(self._open_detail)

        self.stack.setCurrentWidget(self.home)
        QTimer.singleShot(0, self.home.reset)

    def _go_home(self) -> None:
        self.stack.setCurrentWidget(self.home)
        self.home.reset()

    def _open_detail(self, game_id: int) -> None:
        try:
            game = self.backend.details(game_id)
        except Exception as e:
            QMessageBox.warning(self, "Network error", str(e))
            return
        if not game:
            QMessageBox.warning(self, "Not found", "That game isn't in the dataset.")
            return
        self.detail.show_game(game)
        self.stack.setCurrentWidget(self.detail)

    def _open_recs(self, source_id: int) -> None:
        try:
            recs = self.backend.recommend(source_id, 9)
            source = self.backend.details(source_id)
        except Exception as e:
            QMessageBox.warning(self, "Network error", str(e))
            return
        if not source or not recs:
            QMessageBox.warning(self, "No recommendations", "Couldn't generate recommendations.")
            return
        self.recs.show_for(source, recs)
        self.stack.setCurrentWidget(self.recs)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PlayStation Game Recommender")
    app.setStyleSheet(QSS)

    # Default app font
    f = app.font()
    f.setPointSize(10)
    app.setFont(f)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
