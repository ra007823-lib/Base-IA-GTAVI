"""Identidade visual: paleta noturna com neon e folha de estilo do app."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0B0A14"
PANEL = "#17152A"
INPUT = "#100E1E"
BORDER = "#2A2746"
PINK = "#FF3D9A"
CYAN = "#2DE2E6"
ORANGE = "#FF9F45"
TEXT = "#F2F2F2"
MUTED = "#9391A8"
DANGER = "#FF5C6C"
OK = "#4ADE80"

# estado -> (rótulo, cor)
STATUS = {
    "novo": ("Novo", CYAN),
    "analisado": ("Analisado", OK),
    "erro": ("Erro", DANGER),
    "nova": ("Nova", CYAN),
    "selecionada": ("Selecionada", PINK),
    "descartada": ("Descartada", MUTED),
    "usada": ("Usada", OK),
    "usado": ("Usado", MUTED),
    "indisponivel": ("Vídeo já usado", MUTED),
    "em_roteiro": ("Em roteiro", CYAN),
    "aguardando_gravacao": ("Aguardando gravação", ORANGE),
    "gravado": ("Gravado", PINK),
    "aguardando_revisao": ("Aguardando revisão", ORANGE),
    "aprovado": ("Aprovado", OK),
    "rejeitado": ("Rejeitado", DANGER),
    "rascunho": ("Rascunho", MUTED),
    "agendado": ("Agendado", ORANGE),
    "publicado": ("Publicado", OK),
    "sem_autorizacao": ("Só curiosidades", MUTED),
    "autorizado": ("Autorizado", OK),
    "ativo": ("Ativo", OK),
    "pausado": ("Pausado", MUTED),
}

QSS = f"""
QWidget {{ color: {TEXT}; font-size: 14px; }}
QMainWindow, QDialog, QWidget#Page, QScrollArea, QWidget#ScrollBody {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel#H1 {{ font-size: 24px; font-weight: 700; }}
QLabel#H2 {{ font-size: 16px; font-weight: 600; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#StatValue {{ font-size: 30px; font-weight: 700; }}
QLabel#Brand {{ font-size: 20px; font-weight: 700; }}
QLabel#DemoBadge {{
    color: {ORANGE}; border: 1px solid {ORANGE}; border-radius: 8px;
    padding: 6px 8px; font-size: 12px; font-weight: 600;
}}

QWidget#Sidebar {{ background: {INPUT}; border-right: 1px solid {BORDER}; }}
QPushButton#Nav {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 8px;
    color: {MUTED}; background: transparent;
}}
QPushButton#Nav:hover {{ color: {TEXT}; background: {PANEL}; }}
QPushButton#Nav:checked {{
    color: {TEXT}; background: {PANEL}; border-left: 3px solid {PINK}; font-weight: 600;
}}

QFrame#Card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QWidget#TaskStrip {{ background: {INPUT}; border-top: 1px solid {BORDER}; }}

QPushButton {{
    background: #221F3B; border: 1px solid #34305A; border-radius: 8px; padding: 8px 14px;
}}
QPushButton:hover {{ border-color: {CYAN}; }}
QPushButton:focus {{ border-color: {CYAN}; }}
QPushButton:disabled {{ color: #5D5B73; border-color: {BORDER}; background: {PANEL}; }}
QPushButton#Primary {{ background: {PINK}; color: {BG}; border: none; font-weight: 700; }}
QPushButton#Primary:hover {{ background: #FF5FAD; }}
QPushButton#Primary:disabled {{ background: #5A2A45; color: #1B1830; }}

QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateTimeEdit {{
    background: {INPUT}; border: 1px solid #34305A; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {PINK}; selection-color: {BG};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QDateTimeEdit:focus {{ border-color: {CYAN}; }}
QComboBox QAbstractItemView {{
    background: {PANEL}; border: 1px solid {BORDER}; selection-background-color: #2C2850;
}}

QTableWidget, QTreeWidget, QListWidget {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; outline: none;
}}
QTableWidget::item, QTreeWidget::item, QListWidget::item {{ padding: 6px; }}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: #2C2850; color: {TEXT};
}}
QHeaderView::section {{
    background: {PANEL}; color: {MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 8px; font-weight: 600;
}}

QProgressBar {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 6px;
    min-height: 10px; max-height: 10px;
}}
QProgressBar::chunk {{ background: {CYAN}; border-radius: 5px; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; background: {PANEL}; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 8px 18px; border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {PINK}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #34305A; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #34305A; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QRadioButton, QCheckBox {{ background: transparent; spacing: 8px; }}
QRadioButton::indicator {{
    width: 12px; height: 12px; border-radius: 8px;
    border: 2px solid {MUTED}; background: {INPUT};
}}
QRadioButton::indicator:checked {{
    border-color: {PINK};
    background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
        stop: 0 {PINK}, stop: 0.55 {PINK}, stop: 0.6 {INPUT}, stop: 1 {INPUT});
}}
QRadioButton::indicator:disabled {{ border-color: #3A3758; }}

QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::down-button {{ width: 20px; border: none; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 0; height: 0; border-left: 4px solid {INPUT}; border-right: 4px solid {INPUT};
    border-bottom: 5px solid {MUTED};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 0; height: 0; border-left: 4px solid {INPUT}; border-right: 4px solid {INPUT};
    border-top: 5px solid {MUTED};
}}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, BG),
        (QPalette.ColorRole.Base, INPUT),
        (QPalette.ColorRole.AlternateBase, PANEL),
        (QPalette.ColorRole.Button, PANEL),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.PlaceholderText, MUTED),
        (QPalette.ColorRole.Highlight, PINK),
        (QPalette.ColorRole.HighlightedText, BG),
        (QPalette.ColorRole.ToolTipBase, PANEL),
        (QPalette.ColorRole.ToolTipText, TEXT),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(QSS)
