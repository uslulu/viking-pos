"""
Вспомогательный модуль для вызова системной экранной клавиатуры Windows
при фокусе на текстовых полях (для touchscreen).
"""
import subprocess
import os
from PyQt6.QtWidgets import QLineEdit, QTextEdit, QApplication
from PyQt6.QtCore import QObject, QEvent

TABTIP_PATH = r"C:\Program Files\Common Files\microsoft shared\ink\TabTip.exe"
TABTIP_PATH_X86 = r"C:\Program Files (x86)\Common Files\microsoft shared\ink\TabTip.exe"


def show_keyboard():
    """Показать сенсорную клавиатуру Windows"""
    for path in [TABTIP_PATH, TABTIP_PATH_X86]:
        if os.path.exists(path):
            try:
                subprocess.Popen(path)
                return
            except:
                pass
    # Fallback: osk.exe (старая экранная клавиатура)
    try:
        subprocess.Popen('osk.exe')
    except:
        pass


class KeyboardFilter(QObject):
    """
    Устанавливается как eventFilter на QApplication.
    При фокусе на QLineEdit автоматически показывает клавиатуру.
    """
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn:
            if isinstance(obj, (QLineEdit, QTextEdit)):
                # Не вызываем для полей только для чтения (нумпад в оплате)
                if isinstance(obj, QLineEdit) and obj.isReadOnly():
                    return False
                show_keyboard()
        return False


# Глобальный фильтр — устанавливается один раз при старте
_filter = None

def install(app):
    """Вызвать один раз после создания QApplication"""
    global _filter
    _filter = KeyboardFilter()
    app.installEventFilter(_filter)
