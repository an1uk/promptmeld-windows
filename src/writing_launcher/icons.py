from __future__ import annotations

import hashlib
import shutil
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .models import WritingAction


class ActionIconProvider:
    IMAGE_SUFFIXES = {".png", ".svg", ".ico", ".jpg", ".jpeg", ".bmp", ".webp"}
    CATALOG = (
        ("Sparkles", "lucide:sparkles"),
        ("Magic wand", "lucide:wand-sparkles"),
        ("Pencil", "lucide:pencil"),
        ("Edit document", "lucide:file-pen-line"),
        ("Scissors", "lucide:scissors"),
        ("Shrink", "lucide:shrink"),
        ("Expand", "lucide:expand"),
        ("Search and check", "lucide:search-check"),
        ("Spelling", "lucide:spell-check-2"),
        ("Proofread", "lucide:book-open-check"),
        ("Professional", "lucide:briefcase-business"),
        ("Formal", "lucide:landmark"),
        ("Friendly", "lucide:smile"),
        ("Warm", "lucide:heart"),
        ("Message", "lucide:message-square-text"),
        ("Language", "lucide:languages"),
        ("Checklist", "lucide:list-checks"),
        ("Undo", "lucide:rotate-ccw"),
        ("Send", "lucide:send"),
        ("Text input", "lucide:text-cursor-input"),
    )

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._cache: dict[tuple[str, str, int], QIcon] = {}
        self._folder_cache: dict[tuple[str, str, int], QIcon] = {}

    def clear_cache(self) -> None:
        self._cache.clear()
        self._folder_cache.clear()

    def icon_for(self, action: WritingAction, size: int = 36) -> QIcon:
        spec = action.icon.strip() or action.name[:1].upper()
        return self.icon_for_spec(spec, action.id, size)

    def icon_for_spec(self, spec: str, action_id: str, size: int = 36) -> QIcon:
        spec = spec.strip() or action_id[:1].upper()
        key = (action_id, spec, size)
        if key not in self._cache:
            path = self.resolve_image(spec)
            if path is not None:
                icon = (
                    self._lucide_icon(path, action_id, size)
                    if spec.startswith("lucide:")
                    else QIcon(str(path))
                )
                if icon.isNull():
                    icon = self._glyph_icon(spec, action_id, size)
            else:
                icon = self._glyph_icon(spec, action_id, size)
            self._cache[key] = icon
        return self._cache[key]

    def folder_icon_for(
        self,
        folder_path: str,
        badge_spec: str = "",
        size: int = 36,
    ) -> QIcon:
        key = (folder_path, badge_spec, size)
        if key in self._folder_cache:
            return self._folder_cache[key]

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outline = QColor("#b77b24")
        fill = QColor("#e5ad43")
        painter.setPen(outline)
        painter.setBrush(fill)
        painter.drawRoundedRect(
            QRectF(size * 0.08, size * 0.27, size * 0.84, size * 0.62),
            size * 0.09,
            size * 0.09,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            QRectF(size * 0.12, size * 0.13, size * 0.38, size * 0.28),
            size * 0.07,
            size * 0.07,
        )
        if badge_spec.strip():
            badge_size = max(14, int(size * 0.5))
            badge = self.icon_for_spec(
                badge_spec,
                f"folder:{folder_path}",
                badge_size,
            ).pixmap(badge_size, badge_size)
            painter.drawPixmap(
                size - badge_size,
                size - badge_size,
                badge,
            )
        painter.end()
        icon = QIcon(pixmap)
        self._folder_cache[key] = icon
        return icon

    def resolve_image(self, spec: str) -> Path | None:
        if not spec:
            return None
        if spec.startswith("lucide:"):
            name = spec.partition(":")[2]
            if not name or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name):
                return None
            resource = files("writing_launcher").joinpath(
                "resources", "icons", "lucide", f"{name}.svg"
            )
            candidate = Path(str(resource))
            return candidate if candidate.is_file() else None
        candidate = Path(spec).expanduser()
        if not candidate.is_absolute():
            candidate = self.data_dir / candidate
        if (
            candidate.suffix.casefold() in self.IMAGE_SUFFIXES
            and candidate.is_file()
        ):
            return candidate
        return None

    def install_image(self, source: Path) -> str:
        source = source.resolve()
        if source.suffix.casefold() not in self.IMAGE_SUFFIXES:
            raise ValueError("Choose a PNG, SVG, ICO, JPG, BMP, or WebP image.")
        icon_dir = self.data_dir / "icons"
        icon_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:10]
        destination = icon_dir / f"{source.stem}-{digest}{source.suffix.casefold()}"
        if not destination.exists():
            shutil.copy2(source, destination)
        return destination.relative_to(self.data_dir).as_posix()

    @staticmethod
    def _lucide_icon(path: Path, action_id: str, size: int) -> QIcon:
        svg = path.read_text(encoding="utf-8").replace("currentColor", "#ffffff")
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not renderer.isValid():
            return QIcon()

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hue = int(hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:4], 16) % 360
        painter.setBrush(QColor.fromHsv(hue, 115, 205))
        painter.setPen(Qt.PenStyle.NoPen)
        radius = max(6, size // 4)
        painter.drawRoundedRect(1, 1, size - 2, size - 2, radius, radius)
        margin = max(6, int(size * 0.22))
        renderer.render(
            painter,
            QRectF(margin, margin, size - (margin * 2), size - (margin * 2)),
        )
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _glyph_icon(glyph: str, action_id: str, size: int) -> QIcon:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hue = int(hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:4], 16) % 360
        background = QColor.fromHsv(hue, 115, 205)
        painter.setBrush(background)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = max(6, size // 4)
        painter.drawRoundedRect(1, 1, size - 2, size - 2, radius, radius)

        painter.setPen(QColor("white"))
        font = QFont("Segoe UI Emoji")
        font.setPixelSize(max(13, int(size * 0.48)))
        font.setBold(len(glyph) == 1 and glyph.isalnum())
        painter.setFont(font)
        painter.drawText(
            pixmap.rect().adjusted(2, 1, -2, -1),
            Qt.AlignmentFlag.AlignCenter,
            glyph[:4],
        )
        painter.end()
        return QIcon(pixmap)
