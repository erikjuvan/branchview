"""Shared dark colors for application windows and their child dialogs."""
from PySide6.QtGui import QColor, QPalette


DARK_STYLESHEET = '''
    QWidget { background: #252526; color: #cccccc; }
    QLineEdit, QTextEdit, QPlainTextEdit, QAbstractItemView, QComboBox {
        background: #1e1e1e; color: #cccccc; border: 1px solid #3c3c3c;
        selection-background-color: #007acc; selection-color: #ffffff;
    }
    QPushButton {
        background: #2d2d30; color: #cccccc; border: 1px solid #555555;
        border-radius: 3px; padding: 5px 12px;
    }
    QPushButton:hover { background: #37373d; }
    QPushButton:pressed { background: #094771; }
    QPushButton:focus, QPushButton:default { border-color: #007acc; }
    QWidget:disabled { color: #808080; }
    QPushButton:disabled { background: #252526; border-color: #3c3c3c; }
    QHeaderView::section { background: #2d2d30; color: #cccccc; border: 1px solid #3c3c3c; }
    QMenu { background: #252526; color: #cccccc; border: 1px solid #454545; }
    QMenu::item:selected { background: #094771; }
    QToolTip { background: #252526; color: #cccccc; border: 1px solid #454545; }
    QScrollBar { background: #1e1e1e; }
    QScrollBar::handle { background: #424242; border-radius: 4px; }
    QScrollBar::handle:hover { background: #4f4f4f; }
    QScrollBar::handle:vertical { min-height: 24px; }
    QScrollBar::handle:horizontal { min-width: 24px; }
    QScrollBar::add-page, QScrollBar::sub-page { background: none; }
    QSplitter::handle { background: #3c3c3c; }
'''


def apply_dark_theme(widget, extra_styles=''):
    # A palette also covers native-style controls not explicitly styled above.
    palette = widget.palette()
    for role, color in (
        (QPalette.ColorRole.Window, '#252526'),
        (QPalette.ColorRole.WindowText, '#cccccc'),
        (QPalette.ColorRole.Base, '#1e1e1e'),
        (QPalette.ColorRole.AlternateBase, '#2d2d30'),
        (QPalette.ColorRole.Text, '#cccccc'),
        (QPalette.ColorRole.Button, '#2d2d30'),
        (QPalette.ColorRole.ButtonText, '#cccccc'),
        (QPalette.ColorRole.Highlight, '#007acc'),
        (QPalette.ColorRole.HighlightedText, '#ffffff'),
        (QPalette.ColorRole.ToolTipBase, '#252526'),
        (QPalette.ColorRole.ToolTipText, '#cccccc'),
        (QPalette.ColorRole.Link, '#3794ff'),
    ):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor('#808080'))
    widget.setPalette(palette)
    widget.setStyleSheet(DARK_STYLESHEET + extra_styles)
