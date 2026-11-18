"""Componentes reutilizados pelas telas."""

from __future__ import annotations

from pathlib import Path

from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import (
    QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..security import is_allowed_url
from . import theme


def label(text: str, name: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


def button(text: str, on_click, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        widget.setObjectName("Primary")
    widget.clicked.connect(lambda: on_click())
    return widget


def row(*widgets: QWidget, stretch: bool = True) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(10)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch:
        layout.addStretch(1)
    return layout


class Card(QFrame):
    """Painel com título opcional. Use card.body para adicionar conteúdo."""

    def __init__(self, title: str = "") -> None:
        super().__init__()
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(10)
        if title:
            self.body.addWidget(label(title, "H2"))


class Page(QWidget):
    """Base das telas: cabeçalho com título e descrição."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 24, 28, 20)
        self.root.setSpacing(14)
        self.root.addWidget(label(title, "H1"))
        self.root.addWidget(label(subtitle, "Muted"))

    def refresh(self) -> None:  # sobrescrito pelas telas
        pass


def status_text(status: str) -> tuple[str, str]:
    return theme.STATUS.get(status, (status, theme.MUTED))


def chip(status: str) -> QLabel:
    text, color = status_text(status)
    widget = QLabel(text)
    widget.setStyleSheet(
        f"color: {color}; border: 1px solid {color}; border-radius: 9px;"
        " padding: 2px 10px; font-size: 12px; font-weight: 600;"
    )
    widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return widget


def clear_layout(layout) -> None:
    """Remove e destrói todos os itens de um layout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            # Sem o setParent(None) o componente continua desenhado até o Qt destruí-lo.
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def make_table(headers: Sequence[str], stretch_column: int = 0) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return table


def fill_table(table: QTableWidget, rows: Sequence[tuple[int, Sequence]]) -> None:
    """Preenche a tabela. Cada linha é (id, células); célula é texto ou ('estado', valor)."""
    selected = selected_id(table)
    table.setRowCount(len(rows))
    for r, (row_id, cells) in enumerate(rows):
        for c, cell in enumerate(cells):
            if isinstance(cell, tuple):
                text, color = status_text(cell[1])
                item = QTableWidgetItem(f"● {text}")
                item.setForeground(QColor(color))
            else:
                item = QTableWidgetItem(str(cell))
                item.setToolTip(str(cell))
            item.setData(Qt.ItemDataRole.UserRole, row_id)
            table.setItem(r, c, item)
        if row_id == selected:
            table.selectRow(r)


def selected_id(table: QTableWidget) -> int | None:
    items = table.selectedItems()
    return items[0].data(Qt.ItemDataRole.UserRole) if items else None


def fmt_time(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def fmt_date(iso: str) -> str:
    """2026-11-16T09:10:00 -> 16/11/2026 09:10"""
    if len(iso) < 16:
        return iso or "—"
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]} {iso[11:16]}"


def open_url(parent: QWidget, url: str) -> None:
    """Abre no navegador apenas links https dos sites permitidos."""
    if not is_allowed_url(url):
        warn(parent, "Este link não está na lista de sites permitidos e não foi aberto.")
        return
    QDesktopServices.openUrl(QUrl(url))


def warn(parent: QWidget, text: str) -> None:
    QMessageBox.warning(parent, "Atenção", text)


def confirm(parent: QWidget, text: str) -> bool:
    answer = QMessageBox.question(parent, "Confirmar", text)
    return answer == QMessageBox.StandardButton.Yes


_LOGO_FILE = Path(__file__).resolve().parent.parent / "assets" / "macaco.svg"
_renderer = None


def paint_logo(painter: QPainter, rect: QRectF) -> None:
    """Desenha o macaco (SVG no tema neon de pôr do sol) dentro do retângulo."""
    global _renderer
    if _renderer is None:
        _renderer = QSvgRenderer(str(_LOGO_FILE))
    size = min(rect.width(), rect.height())
    square = QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2, size, size)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _renderer.render(painter, square)


def app_icon() -> QIcon:
    pixmap = QPixmap(256, 256)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_logo(painter, QRectF(0, 0, 256, 256))
    painter.end()
    return QIcon(pixmap)


class LogoWidget(QWidget):
    def __init__(self, size: int = 44) -> None:
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802 - nome definido pelo Qt
        painter = QPainter(self)
        paint_logo(painter, QRectF(self.rect()))
        painter.end()
