import sys
import os
import json
import logging
import tomllib
import tomlkit
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QFrame,
    QSizePolicy,
    QMessageBox,
    QCheckBox,
    QLineEdit,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QToolButton,
    QMenu,
    QTabWidget,
    QSpinBox,
    QStylePainter,
    QStyleOptionComboBox,
    QStyle,
    QProgressDialog,
    QDialog,
    QTextBrowser,
    QProgressBar,
)
from PyQt6.QtWidgets import QAbstractScrollArea
from PyQt6.QtCore import Qt, QSize, QTimeZone, QSettings, QLocale, QObject, QThread, pyqtSignal, QEventLoop, QTimer
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont, QColor, QPixmap, QIcon
import qtawesome as qta
from PyQt6.QtSvgWidgets import QSvgWidget

LOGGER = logging.getLogger("tg2tc")

import parse_users
LOGGER.info("parse_users imported successfully")
import add_users_to_server
LOGGER.info("add_users_to_server imported successfully")
import build_chat
LOGGER.info("build_chat imported successfully")
from localization import _, setup_i18n

try:
    import pyi_splash
except ImportError:
    pyi_splash = None


def get_resource_path(relative_path: str) -> str:
    """
    Возвращает абсолютный путь к ресурсу.
    Работает как в разработке, так и в собранном .exe (onefile).
    """
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def get_work_dir() -> Path:
    r"""
    Возвращает рабочую директорию для логов, конфигов и временных файлов.
    - Windows: %LOCALAPPDATA%\TrueConf\tg2tc
    - macOS/Linux: ~/.tg2tc
    """
    if sys.platform.startswith("win"):
        localappdata = os.getenv("LOCALAPPDATA")
        base_dir = (
            Path(localappdata) if localappdata else Path.home() / "AppData" / "Local"
        )
        return base_dir / "TrueConf" / "tg2tc"
    return Path.home() / ".tg2tc"


def setup_file_logging() -> Path:
    config_dir = get_work_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    log_path = config_dir / "app.log"

    if LOGGER.handlers:
        return log_path

    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    LOGGER.addHandler(file_handler)
    LOGGER.propagate = False
    LOGGER.info("=== Application started ===")
    return log_path

class ChatTransferProgressDialog(QDialog):
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._allow_close = False

    def allow_close(self):
        self._allow_close = True

    def closeEvent(self, event):
        if not self._allow_close:
            self.cancel_requested.emit()
            event.ignore()
            return
        super().closeEvent(event)

class ChatTransferWorker(QObject):
    progress_changed = pyqtSignal(int, int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    canceled = pyqtSignal()

    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def _append_log(self, seen_logs: set[str], text: str):
        clean_text = str(text).strip()
        if not clean_text:
            return
        if clean_text in seen_logs:
            return
        seen_logs.add(clean_text)
        self.log_message.emit(clean_text)

    def run(self):
        seen_logs: set[str] = set()

        try:

            def progress_callback(current: int, total: int):
                if self._cancel_requested:
                    raise RuntimeError("CHAT_TRANSFER_CANCELED")
                self.progress_changed.emit(int(current), int(total))

            def log_callback(text: str):
                if self._cancel_requested:
                    raise RuntimeError("CHAT_TRANSFER_CANCELED")
                self._append_log(seen_logs, text)

            result = None
            if hasattr(build_chat, "run_chat_transfer") and callable(
                build_chat.run_chat_transfer
            ):
                LOGGER.info(
                    f"Starting run_chat_transfer with config_path: {self.config_path}"
                )
                LOGGER.info(f"Config file exists: {Path(self.config_path).exists()}")
                LOGGER.info(f"Current working directory: {Path.cwd()}")
                result = build_chat.run_chat_transfer(
                    self.config_path,
                    progress_callback=progress_callback,
                    log_callback=log_callback,
                    should_cancel=lambda: self._cancel_requested,
                )
            elif hasattr(build_chat, "main") and callable(build_chat.main):
                LOGGER.info("Starting build_chat.main")
                result = build_chat.main(
                    self.config_path,
                    progress_callback=progress_callback,
                    log_callback=log_callback,
                    should_cancel=lambda: self._cancel_requested,
                )
            else:
                raise RuntimeError("В build_chat.py не найдена функция run_chat_transfer")

            if self._cancel_requested:
                self.canceled.emit()
                return

            self.finished.emit(result or {"status": "ok"})
        except RuntimeError as error:
            if str(error) == "CHAT_TRANSFER_CANCELED":
                LOGGER.info("Chat transfer canceled by user")
                self.canceled.emit()
                return
            LOGGER.exception("Chat transfer failed with runtime error")
            self.failed.emit(str(error))
        except Exception as error:
            LOGGER.exception("Chat transfer failed")
            self.failed.emit(str(error))

class BackgroundTaskWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as error:
            LOGGER.exception("Background task failed")
            self.failed.emit(str(error))

class ElidedComboBox(QComboBox):
    """QComboBox with elided current text."""

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)

        original_text = self.currentData(Qt.ItemDataRole.UserRole)
        if original_text is None:
            original_text = self.currentText()

        text_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        elided = option.fontMetrics.elidedText(
            str(original_text),
            Qt.TextElideMode.ElideRight,
            max(20, text_rect.width()),
        )
        option.currentText = elided

        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)


class ResizableTable(QTableWidget):
    """QTableWidget, который вызывает _resize_user_table_columns при изменении размера."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "_resize_user_table_columns"):
                parent._resize_user_table_columns()
                break
            parent = parent.parent()


class MutedHeaderView(QHeaderView):
    """Заголовок таблицы с приглушённым оформлением для колонок Telegram-бота."""

    MUTED_COLUMNS = {5, 6}

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)

    def paintSection(self, painter, rect, logicalIndex):
        if logicalIndex in self.MUTED_COLUMNS:
            painter.save()
            painter.fillRect(rect, QColor("#F3F4F6"))
            painter.setPen(QColor("#D7E9EE"))
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
            painter.drawLine(rect.topRight(), rect.bottomRight())
            painter.setPen(QColor("#0088CC"))
            font = self.font()
            font.setPixelSize(12)
            font.setBold(True)
            painter.setFont(font)
            text = self.model().headerData(logicalIndex, self.orientation(), Qt.ItemDataRole.DisplayRole)
            text_rect = rect.adjusted(0, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, str(text) if text else "")
            painter.restore()
        else:
            super().paintSection(painter, rect, logicalIndex)


class DragDropArea(QFrame):
    """Красивая зона приема папок через drag and drop"""

    def __init__(self, parent=None, on_folder_dropped=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.on_folder_dropped = on_folder_dropped
        self._is_drag_active = False
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(64, 64)
        self.icon_label.setStyleSheet("background: transparent; border: none;")

        folder_pixmap = QPixmap(get_resource_path("assets/folder.png"))
        self.icon_label.setPixmap(
            folder_pixmap.scaled(
                64,
                64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        self.title_label = QLabel(_("first_screen.drop_here"))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(False)
        self.title_label.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: #163047; background: transparent; border: none;"
        )

        self.subtitle_label = QLabel(_("first_screen.export_from"))
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setStyleSheet(
            "font-size: 14px; color: #5E7486; background: transparent; border: none;"
        )

        layout.addSpacing(18)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addSpacing(18)

    def _apply_style(self):
        if self._is_drag_active:
            self.setStyleSheet(
                """
                QFrame {
                    background-color: #EAF8FB;
                    border: 2px dashed #3BB4C8;
                    border-radius: 24px;
                }
                """
            )
        else:
            self.setStyleSheet(
                """
                QFrame {
                    background-color: #FFFFFF;
                    border: 2px dashed #B9D7E0;
                    border-radius: 24px;
                }
                """
            )

    @staticmethod
    def _extract_folder(event):
        urls = event.mimeData().urls()
        if not urls:
            return None

        local_file = urls[0].toLocalFile()
        if local_file and Path(local_file).is_dir():
            return local_file
        return None

    def dragEnterEvent(self, event: QDragEnterEvent):
        folder = self._extract_folder(event)
        if folder:
            self._is_drag_active = True
            self._apply_style()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragEnterEvent):
        folder = self._extract_folder(event)
        if folder:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._is_drag_active = False
        self._apply_style()
        event.accept()

    def dropEvent(self, event: QDropEvent):
        folder = self._extract_folder(event)
        self._is_drag_active = False
        self._apply_style()

        if folder:
            event.acceptProposedAction()
            if self.on_folder_dropped:
                self.on_folder_dropped(folder)
        else:
            event.ignore()


class FirstScreen(QWidget):
    """Первый экран - выбор папки с бекапом"""

    def __init__(self, on_folder_selected):
        super().__init__()
        self.on_folder_selected = on_folder_selected
        self.settings = QSettings("TrueConf", "tg2tc")
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("background-color: #F6FAFC;")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(32, 24, 32, 24)
        root_layout.setSpacing(0)

        card = QFrame()
        card.setObjectName("mainCard")
        card.setStyleSheet(
            """
            QFrame#mainCard {
                background-color: #FFFFFF;
                border: 1px solid #E2EEF2;
                border-radius: 28px;
            }
            """
        )
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(34, 28, 34, 28)
        card_layout.setSpacing(14)

        brand_label = QSvgWidget(get_resource_path("assets/trueconf-logo.svg"))
        logo_size = brand_label.renderer().defaultSize()
        scaled_logo_size = logo_size.scaled(
            QSize(225, 45),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        brand_label.setFixedSize(scaled_logo_size)
        brand_label.setStyleSheet("background: transparent;")

        current_lang = self.settings.value("lang", "ru")

        self.lang_button = QToolButton()
        self.lang_button.setText("🌐")
        self.lang_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_button.setFixedSize(42, 42)
        self.lang_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.lang_button.setStyleSheet(
            """
            QToolButton {
                background-color: #EAF8FB;
                color: #3097A6;
                border: 1px solid #B9E5EC;
                border-radius: 21px;
                font-size: 20px;
                padding: 0;
            }
            QToolButton:hover {
                background-color: #DDF5F8;
                border: 1px solid #3BB4C8;
            }
            QToolButton::menu-indicator {
                width: 0;
                height: 0;
            }
            """
        )

        lang_menu = QMenu(self.lang_button)
        lang_menu.setStyleSheet(
            """
            QMenu {
                background-color: #FFFFFF;
                color: #163047;
                border: 1px solid #D7E9EE;
                border-radius: 10px;
                padding: 6px;
                font-size: 14px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #EAF8FB;
                color: #163047;
            }
            """
        )

        for lang_code, lang_label in [("ru", "🇷🇺  Русский"), ("en", "🇬🇧  English")]:
            action = lang_menu.addAction(lang_label)
            action.setCheckable(True)
            action.setChecked(lang_code == current_lang)
            action.triggered.connect(lambda checked, code=lang_code: self._on_lang_selected(code))

        self.lang_button.setMenu(lang_menu)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.addWidget(brand_label)
        header_row.addStretch()
        header_row.addWidget(self.lang_button)

        title = QLabel(_("app.title"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setStyleSheet(
            "font-size: 24px; font-weight: 800; color: #163047; background: transparent;"
        )

        self.drop_area = DragDropArea(on_folder_dropped=self.on_folder_selected)
        self.drop_area.setMinimumHeight(250)
        self.drop_area.setMaximumHeight(280)
        self.drop_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(14)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.browse_button = QPushButton(_("first_screen.browse"))
        self.browse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_button.setFixedHeight(52)
        self.browse_button.setMinimumWidth(220)
        self.browse_button.setStyleSheet(
            """
            QPushButton {
                background-color: #3BB4C8;
                color: white;
                border: none;
                border-radius: 14px;
                font-size: 16px;
                font-weight: 700;
                padding: 0 24px;
            }
            QPushButton:hover {
                background-color: #41C2E1;
            }
            QPushButton:pressed {
                background-color: #3097A6;
            }
            """
        )
        self.browse_button.clicked.connect(self.browse_folder)


        buttons_layout.addWidget(self.browse_button)

        card_layout.addLayout(header_row)
        card_layout.addWidget(title)
        card_layout.addSpacing(6)
        card_layout.addWidget(self.drop_area)
        card_layout.addSpacing(14)
        card_layout.addLayout(buttons_layout)
        card_layout.addStretch()

        root_layout.addStretch()
        root_layout.addWidget(card)
        root_layout.addStretch()

    def browse_folder(self):
        last_dir = self.settings.value("last_export_dir", str(Path.home()))

        dialog = QFileDialog(self, _("first_screen.folder_dialog"))
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setDirectory(str(last_dir))

        if dialog.exec():
            selected = dialog.selectedFiles()
            if selected:
                folder = selected[0]
                LOGGER.info("Folder selected: %s", folder)
                self.settings.setValue("last_export_dir", folder)
                self.on_folder_selected(folder)

    def _on_lang_selected(self, lang):
        if lang and lang != self.settings.value("lang", "ru"):
            self.settings.setValue("lang", lang)
            app = QApplication.instance()
            if app:
                app.exit(42)


class SettingsScreen(QWidget):
    """Экран настроек переноса"""

    EMAIL_DOMAIN_TOOLTIP = _("users.email_domain_tooltip")

    def __init__(
        self,
        folder_path,
        config_path,
        on_back,
        on_refresh_users=None,
        on_add_users=None,
        on_run_transfer=None,
    ):
        super().__init__()
        self.folder_path = folder_path
        self.config_path = config_path
        self.on_back = on_back
        self.on_refresh_users = on_refresh_users
        self.on_add_users = on_add_users
        self._is_loading_toml = False
        self._build_ui()
        self._is_loading_toml = True
        self.load_form_from_toml()
        self.load_users_from_toml()
        self._is_loading_toml = False
        self.on_run_transfer = on_run_transfer

    def _mark_dirty(self, *args, **kwargs):
        if getattr(self, "_is_loading_toml", False):
            return
        if hasattr(self, "run_button"):
            self.run_button.setEnabled(False)

    def _create_user_table_item(self, value: str, user_key: str = "", editable: bool = True) -> QTableWidgetItem:
        item = QTableWidgetItem(value)
        if user_key:
            item.setData(Qt.ItemDataRole.UserRole, user_key)
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _apply_registration_password_to_table(self, password: str):
        if getattr(self, "_is_loading_toml", False):
            return

        password = password.strip()
        if not hasattr(self, "users_table"):
            return

        password_column = 3
        self.users_table.blockSignals(True)
        for row in range(self.users_table.rowCount()):
            item = self.users_table.item(row, password_column)
            if item is None:
                item = self._create_user_table_item("", editable=True)
                self.users_table.setItem(row, password_column, item)

            item.setText(password)
        self.users_table.blockSignals(False)

    def _resize_user_table_columns(self):
        table = self.users_table
        min_widths = self._col_min_widths
        total_min = sum(min_widths)
        viewport_width = table.viewport().width()
        extra = max(0, viewport_width - total_min)

        self._is_resizing_columns = True
        for col in range(len(min_widths)):
            new_width = min_widths[col] + extra * self._col_ratios[col]
            table.setColumnWidth(col, int(new_width))
        self._is_resizing_columns = False

    def _on_user_table_section_resized(self, logical_index, _old_size, _new_size):
        if self._is_resizing_columns:
            return
        table = self.users_table
        total = sum(table.columnWidth(c) for c in range(table.columnCount()))
        if total > 0:
            self._col_ratios = [
                table.columnWidth(c) / total for c in range(table.columnCount())
            ]

    def load_form_from_toml(self):
        config_file = Path(self.config_path)
        if not config_file.exists():
            return

        with config_file.open("rb") as file:
            data = tomllib.load(file)

        telegram_bot = data.get("telegram_bot", {}) or {}
        server = data.get("server", {}) or {}
        chat = data.get("chat", {}) or {}
        registration = data.get("registration", {}) or {}
        chat_datetime = chat.get("datetime", {}) or {}
        chat_voice = chat.get("voice_message", {}) or {}
        chat_stickers = chat.get("stickers", {}) or {}

        self.telegram_bot_token_input.setText(str(telegram_bot.get("token", "")))
        self.telegram_bot_chat_id_input.setText(str(telegram_bot.get("chat_id", "")))
        telegram_bot_enabled = telegram_bot.get("enabled", None)
        if telegram_bot_enabled is None:
            telegram_bot_enabled = bool(telegram_bot.get("token", "") or telegram_bot.get("chat_id", ""))
        self.telegram_bot_enrich_checkbox.setChecked(bool(telegram_bot_enabled))
        self._update_telegram_bot_controls_state(self.telegram_bot_enrich_checkbox.isChecked())

        self.server_address_input.setText(str(server.get("address", "")))
        web_port = server.get("web_port", 443)
        try:
            self.server_port_input.setValue(int(web_port))
        except (TypeError, ValueError):
            self.server_port_input.setValue(443)

        verify_ssl = bool(server.get("verify_ssl", False))
        self.server_verify_ssl_combo.setCurrentText(_("server.ssl_on") if verify_ssl else _("server.ssl_off"))
        self.server_access_token_input.setText(str(server.get("access_token", "")))

        self.chat_name_input.setText(str(chat.get("name", "")))

        owner_value = str(chat.get("owner", ""))
        self.owner_input.setText(owner_value)

        chat_type_value = str(chat.get("type", ""))
        if chat_type_value:
            type_index = self.chat_type_combo.findData(chat_type_value)
            if type_index >= 0:
                self.chat_type_combo.setCurrentIndex(type_index)

        self.supergroup_template_input.setText(
            str(chat.get("supergroup_topic_name_template", "{topic} | {supergroup}"))
        )

        voice_enabled = bool(chat_voice.get("convert_voice_message_to_video", False))
        self.voice_checkbox.setChecked(voice_enabled)
        self.cover_input.setText(str(chat_voice.get("cover_image", "cover/ru.png")))

        stickers_enabled = bool(chat_stickers.get("convert_telegram_stickers_to_webp", False))
        self.stickers_checkbox.setChecked(stickers_enabled)

        datetime_enabled = bool(chat_datetime.get("view_original_time_in_message", False))
        self.datetime_checkbox.setChecked(datetime_enabled)

        timezone_value = str(chat_datetime.get("timezone", "GMT"))
        timezone_index = self.timezone_combo.findText(timezone_value)
        if timezone_index >= 0:
            self.timezone_combo.setCurrentIndex(timezone_index)

        self.caption_input.setText(str(chat_datetime.get("caption", _("media.caption_default"))))
        self.registration_password_input.setText(str(registration.get("default_password", "")))
        self.registration_email_domain_input.setText(str(registration.get("email_domain", "")))

        self._update_voice_controls_state(self.voice_checkbox.isChecked())
        self._update_datetime_controls_state(self.datetime_checkbox.isChecked())
        self._update_supergroup_template_state(str(self.chat_type_combo.currentData() or ""))
        if hasattr(self, "run_button"):
            self.run_button.setEnabled(False)
    def load_users_from_toml(self):
        table = getattr(self, "users_table", None)
        if table is None:
            return

        config_file = Path(self.config_path)
        users = {}
        if config_file.exists():
            with config_file.open("rb") as file:
                data = tomllib.load(file)
            users = data.get("users", {}) or {}

        table.blockSignals(True)
        table.setRowCount(0)
        editable_columns = {1, 2, 3, 4}   # display_name, trueconf_id, token, password

        for row_index, (user_key, user_data) in enumerate(users.items()):
            table.insertRow(row_index)
            row_values = [
                str(user_data.get("telegram_id", "")),
                str(user_data.get("trueconf_id", "")),
                str(user_data.get("access_token", "")),
                str(user_data.get("password", "")),
                str(user_data.get("display_name", "")),
                str(user_data.get("real_display_name", "")),
                str(user_data.get("username", "")),
            ]
            for column_index, cell_value in enumerate(row_values):
                item = self._create_user_table_item(
                    cell_value,
                    user_key=user_key if column_index == 0 else "",
                    editable=column_index in editable_columns,
                )
                if column_index == 0:
                    item.setData(
                        Qt.ItemDataRole.UserRole + 1,
                        str(user_data.get("type", "user")),
                    )
                table.setItem(row_index, column_index, item)
        table.blockSignals(False)
        self._apply_user_table_visuals()

        self.add_users_button.setEnabled(table.rowCount() > 0)
        if hasattr(self, "run_button"):
            self.run_button.setEnabled(False)

    def save_form_to_toml(self):
        config_file = Path(self.config_path)
        if config_file.exists():
            with config_file.open("r", encoding="utf-8") as file:
                config = tomlkit.load(file)
        else:
            config = tomlkit.document()

        if "telegram_bot" not in config:
            config["telegram_bot"] = tomlkit.table()
        if "server" not in config:
            config["server"] = tomlkit.table()
        if "chat" not in config:
            config["chat"] = tomlkit.table()
        if "registration" not in config:
            config["registration"] = tomlkit.table()
        if "users" not in config:
            config["users"] = tomlkit.table()

        chat = config["chat"]
        if "datetime" not in chat:
            chat["datetime"] = tomlkit.table()
        if "voice_message" not in chat:
            chat["voice_message"] = tomlkit.table()
        if "stickers" not in chat:
            chat["stickers"] = tomlkit.table()

        config["telegram_export_dir"] = str(self.folder_path)

        config["telegram_bot"]["enabled"] = self.telegram_bot_enrich_checkbox.isChecked()
        config["telegram_bot"]["token"] = self.telegram_bot_token_input.text().strip()
        config["telegram_bot"]["chat_id"] = self.telegram_bot_chat_id_input.text().strip()

        config["server"]["address"] = self.server_address_input.text().strip()
        config["server"]["web_port"] = int(self.server_port_input.value())
        config["server"]["verify_ssl"] = self.server_verify_ssl_combo.currentText() == _("server.ssl_on")
        config["server"]["access_token"] = self.server_access_token_input.text().strip()
        config["registration"]["default_password"] = self.registration_password_input.text().strip()
        config["registration"]["email_domain"] = self.registration_email_domain_input.text().strip()

        chat["name"] = self.chat_name_input.text().strip()
        chat["owner"] = self.owner_input.text().strip()
        chat["type"] = str(self.chat_type_combo.currentData() or "")
        chat["supergroup_topic_name_template"] = self.supergroup_template_input.text().strip()

        chat["datetime"]["view_original_time_in_message"] = self.datetime_checkbox.isChecked()
        chat["datetime"]["timezone"] = self.timezone_combo.currentData(Qt.ItemDataRole.UserRole) or self.timezone_combo.currentText()
        chat["datetime"]["caption"] = self.caption_input.text()

        chat["voice_message"]["convert_voice_message_to_video"] = self.voice_checkbox.isChecked()
        chat["voice_message"]["cover_image"] = self.cover_input.text().strip()

        chat["stickers"]["convert_telegram_stickers_to_webp"] = self.stickers_checkbox.isChecked()

        users_table = tomlkit.table()
        for row in range(self.users_table.rowCount()):
            values = []
            for col in range(self.users_table.columnCount()):
                item = self.users_table.item(row, col)
                values.append(item.text().strip() if item is not None else "")

            telegram_id, trueconf_id, access_token, password, display_name, real_display_name, username = values

            key_item = self.users_table.item(row, 0)
            stored_key = key_item.data(Qt.ItemDataRole.UserRole) if key_item is not None else None
            stored_type = key_item.data(Qt.ItemDataRole.UserRole + 1) if key_item is not None else None
            user_key = str(stored_key).strip() if stored_key else ""
            user_type = str(stored_type).strip() if stored_type else "user"
            if not user_key:
                user_key = trueconf_id or username or telegram_id or f"user_{row + 1}"
            user_key = user_key.replace("@", "").replace(" ", "_")

            user_table = tomlkit.table()
            user_table["display_name"] = display_name
            user_table["password"] = password
            user_table["access_token"] = access_token
            user_table["trueconf_id"] = trueconf_id
            user_table["telegram_id"] = telegram_id
            user_table["type"] = user_type
            user_table["username"] = username
            user_table["real_display_name"] = real_display_name
            users_table[user_key] = user_table

        config["users"] = users_table
        LOGGER.info("Saving config to %s", config_file)
        with config_file.open("w", encoding="utf-8") as file:
            tomlkit.dump(config, file)

    def reload_from_toml(self):
        self.load_form_from_toml()
        self.load_users_from_toml()

    def _collect_manual_user_overrides(self) -> dict[str, dict[str, str]]:
        overrides = {}
        if not hasattr(self, "users_table"):
            return overrides

        for row in range(self.users_table.rowCount()):
            telegram_item = self.users_table.item(row, 0)
            trueconf_item = self.users_table.item(row, 1)
            access_token_item = self.users_table.item(row, 2)
            password_item = self.users_table.item(row, 3)
            display_name_item = self.users_table.item(row, 4)
            real_name_item = self.users_table.item(row, 5)
            username_item = self.users_table.item(row, 6)

            telegram_id = telegram_item.text().strip() if telegram_item is not None else ""
            access_token = access_token_item.text().strip() if access_token_item is not None else ""
            trueconf_id = trueconf_item.text().strip() if trueconf_item is not None else ""
            password = password_item.text().strip() if password_item is not None else ""
            display_name = display_name_item.text().strip() if display_name_item is not None else ""
            real_name = real_name_item.text().strip() if real_name_item is not None else ""
            username = username_item.text().strip() if username_item is not None else ""

            user_key = ""
            if telegram_item is not None:
                stored_key = telegram_item.data(Qt.ItemDataRole.UserRole)
                user_key = str(stored_key).strip() if stored_key else ""

            identifiers = [
                f"key:{user_key}" if user_key else "",
                f"trueconf:{trueconf_id}" if trueconf_id else "",
                f"telegram:{telegram_id}" if telegram_id else "",
                f"username:{username.lstrip('@')}" if username else "",
            ]

            row_data = {
                "display_name": display_name,
                "trueconf_id": trueconf_id,
                "access_token": access_token,
                "password": password,
            }

            for identifier in identifiers:
                if identifier:
                    overrides[identifier] = row_data.copy()

        return overrides

    def _apply_user_table_visuals(self):
        if not hasattr(self, "users_table"):
            return

        table = self.users_table
        registration_active = bool(
            self.registration_password_input.text().strip()
            or self.registration_email_domain_input.text().strip()
        )

        # Find duplicate TrueConf IDs (case-insensitive, non-empty)
        duplicate_trueconf_ids = set()
        trueconf_id_rows: dict[str, list[int]] = {}
        for row in range(table.rowCount()):
            item = table.item(row, 1)
            value = item.text().strip() if item is not None else ""
            if not value:
                continue
            normalized = value.lower()
            trueconf_id_rows.setdefault(normalized, []).append(row)

        for normalized_value, rows in trueconf_id_rows.items():
            if len(rows) > 1:
                duplicate_trueconf_ids.add(normalized_value)

        table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                telegram_id_item = table.item(row, 0)
                trueconf_id_item = table.item(row, 1)
                access_token_item = table.item(row, 2)
                password_item = table.item(row, 3)
                display_name_item = table.item(row, 4)
                real_name_item = table.item(row, 5)
                username_item = table.item(row, 6)

                telegram_id = telegram_id_item.text().strip() if telegram_id_item else ""
                access_token = access_token_item.text().strip() if access_token_item else ""
                trueconf_id = trueconf_id_item.text().strip() if trueconf_id_item else ""
                password = password_item.text().strip() if password_item else ""
                display_name = display_name_item.text().strip() if display_name_item else ""
                normalized_trueconf_id = trueconf_id.lower() if trueconf_id else ""

                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item is None:
                        continue
                    item.setBackground(QColor("#FFFFFF"))
                    item.setForeground(QColor("#163047"))
                    item.setToolTip("")

                for item in (username_item, real_name_item):
                    if item is not None:
                        item.setForeground(QColor("#6B7280"))
                        item.setBackground(QColor("#F9FAFB"))

                if not telegram_id and telegram_id_item is not None:
                    telegram_id_item.setBackground(QColor("#FFF4BF"))
                    telegram_id_item.setToolTip(_("tooltips.no_telegram_id"))

                if not access_token and not (trueconf_id and password):
                    for item in (access_token_item, trueconf_id_item, password_item):
                        if item is not None:
                            item.setBackground(QColor("#FFF4BF"))
                            item.setToolTip(_("tooltips.need_token_or_creds"))

                if registration_active and not display_name and display_name_item is not None:
                    display_name_item.setBackground(QColor("#FFF4BF"))
                    display_name_item.setToolTip(_("tooltips.need_display_name"))

                if normalized_trueconf_id and normalized_trueconf_id in duplicate_trueconf_ids and trueconf_id_item is not None:
                    trueconf_id_item.setBackground(QColor("#FFD9D9"))
                    trueconf_id_item.setForeground(QColor("#A63B3B"))
                    trueconf_id_item.setToolTip(_("tooltips.duplicate_trueconf_id"))
        finally:
            table.blockSignals(False)

    def _restore_manual_user_overrides_to_toml(self, override_map: dict[str, dict[str, str]]):
        if not override_map:
            return

        config_file = Path(self.config_path)
        if not config_file.exists():
            return

        with config_file.open("r", encoding="utf-8") as file:
            config = tomlkit.load(file)

        users = config.get("users", {}) or {}
        changed = False
        for user_key, user_data in users.items():
            identifiers = [
                f"key:{user_key}",
                f"trueconf:{str(user_data.get('trueconf_id', '')).strip()}" if str(user_data.get('trueconf_id', '')).strip() else "",
                f"telegram:{str(user_data.get('telegram_id', '')).strip()}" if str(user_data.get('telegram_id', '')).strip() else "",
                f"username:{str(user_data.get('username', '')).strip().lstrip('@')}" if str(user_data.get('username', '')).strip() else "",
            ]

            matched_override = None
            for identifier in identifiers:
                if identifier and identifier in override_map:
                    matched_override = override_map[identifier]
                    break

            if matched_override is None:
                continue

            for field_name in ("display_name", "trueconf_id", "access_token", "password"):
                new_value = matched_override.get(field_name, "")
                if str(user_data.get(field_name, "")) != new_value:
                    user_data[field_name] = new_value
                    changed = True

        if changed:
            with config_file.open("w", encoding="utf-8") as file:
                tomlkit.dump(config, file)

    def _refresh_users(self):
        if self.on_refresh_users is None:
            return

        if self.telegram_bot_enrich_checkbox.isChecked():
            token = self.telegram_bot_token_input.text().strip()
            chat_id = self.telegram_bot_chat_id_input.text().strip()
            if not token or not chat_id:
                self.tabs.setCurrentIndex(0)
                QMessageBox.information(
                    self,
                    _("dialogs.bot_data_needed"),
                    _("dialogs.bot_data_needed_msg"),
                )
                return

        try:
            LOGGER.info("Refreshing users for config: %s", self.config_path)
            manual_overrides = self._collect_manual_user_overrides()
            self.save_form_to_toml()
            self.on_refresh_users(self.config_path)
            self._restore_manual_user_overrides_to_toml(manual_overrides)
            self.load_users_from_toml()
            LOGGER.info("Users refresh completed for config: %s", self.config_path)
        except Exception as error:
            LOGGER.exception("Failed to refresh users for config: %s", self.config_path)
            QMessageBox.warning(
                self,
                _("dialogs.refresh_error"),
                f"{_('dialogs.refresh_error_msg', error=error)}",
            )

    def _add_users_to_server(self):
        if self.on_add_users is None:
            return

        try:
            LOGGER.info("Starting server user registration for config: %s", self.config_path)
            self.save_form_to_toml()
            result = self.on_add_users(self.config_path)

            created = result.get("created", []) if isinstance(result, dict) else []
            already_exists = result.get("already_exists", []) if isinstance(result, dict) else []
            errors = result.get("errors", []) if isinstance(result, dict) else []

            def escape_html(value: str) -> str:
                return (
                    str(value)
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )

            def format_user_line(entry: dict) -> str:
                display_name = str(entry.get("display_name", "")).strip()
                trueconf_id = str(entry.get("trueconf_id", "")).strip()
                telegram_id = str(entry.get("telegram_id", "")).strip()
                user_key = str(entry.get("user", "")).strip()

                parts = []
                if display_name:
                    parts.append(escape_html(display_name))
                if trueconf_id:
                    parts.append(f"TrueConf ID: {escape_html(trueconf_id)}")
                if telegram_id:
                    parts.append(f"Telegram ID: {escape_html(telegram_id)}")
                if not parts and user_key:
                    parts.append(escape_html(user_key))
                return " — ".join(parts)

            def format_section(title: str, items: list[dict], icon: str) -> str:
                if not items:
                    return ""

                rows = []
                for entry in items:
                    rows.append(
                        "<div style='padding:10px 12px;'>"
                        + format_user_line(entry)
                        + "</div>"
                    )
                body = "<hr style='border:none; border-top:1px solid #E2EEF2; margin:0;'>".join(rows)
                return (
                    f"<div style='margin-bottom:18px;'>"
                    f"<div style='font-size:14px; font-weight:700; color:#163047; margin-bottom:8px;'>{icon} {escape_html(title)} ({len(items)})</div>"
                    f"<div style='border:1px solid #D7E9EE; border-radius:12px; background:#FFFFFF; overflow:hidden;'>"
                    f"{body}"
                    f"</div>"
                    f"</div>"
                )

            error_section = ""
            if errors:
                error_rows = []
                for error in errors:
                    user = escape_html(error.get("user", "—"))
                    status_code = escape_html(error.get("status_code", "—"))
                    message = escape_html(error.get("message", _("dialogs.unknown_error")))
                    details = escape_html(error.get("details", ""))
                    line = f"{user} — {status_code} — {message}"
                    if details and details != "—":
                        line += f" ({details})"
                    error_rows.append(
                        "<div style='padding:10px 12px;'>" + line + "</div>"
                    )
                error_body = "<hr style='border:none; border-top:1px solid #E2EEF2; margin:0;'>".join(error_rows)
                error_section = (
                    f"<div style='margin-bottom:18px;'>"
                    f"<div style='font-size:14px; font-weight:700; color:#163047; margin-bottom:8px;'>🔴 {_('results.errors')} ({len(errors)})</div>"
                    f"<div style='border:1px solid #D7E9EE; border-radius:12px; background:#FFFFFF; overflow:hidden;'>"
                    f"{error_body}"
                    f"</div>"
                    f"</div>"
                )

            sections = []
            created_section = format_section(_("results.registered"), created, "✅")
            already_exists_section = format_section(_("results.already_exist"), already_exists, "⚠️")
            if created_section:
                sections.append(created_section)
            if already_exists_section:
                sections.append(already_exists_section)
            if error_section:
                sections.append(error_section)

            if not sections:
                sections.append(
                    "<div style='font-size:13px; color:#5E7486;'>"
                    + _("results.no_details")
                    + "</div>"
                )

            html = (
                "<html><body style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; "
                "font-size:13px; color:#163047; background:#FFFFFF; margin:12px;'>"
                + "".join(sections)
                + "</body></html>"
            )

            self._show_registration_results_popup(
                _("results.registration_title"),
                html,
            )
        except Exception as error:
            LOGGER.exception("Failed to register users on server for config: %s", self.config_path)
            QMessageBox.warning(
                self,
                _("dialogs.register_error"),
                f"{_('dialogs.register_error_msg', error=error)}",
            )

    def _show_registration_results_popup(self, title_text: str, details_html: str):
        dialog = QDialog(self)
        dialog.setWindowTitle(title_text)
        dialog.setWindowIcon(QIcon(get_resource_path("assets/icon.png")))
        dialog.setModal(True)
        dialog.resize(820, 560)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: #FFFFFF;
            }
            QLabel {
                color: #163047;
                background: transparent;
            }
            QTextBrowser {
                background-color: #FFFFFF;
                color: #163047;
                border: 1px solid #D7E9EE;
                border-radius: 12px;
                padding: 0;
                font-size: 13px;
            }
            QPushButton {
                background-color: #EAF8FB;
                color: #3097A6;
                border: 1px solid #B9E5EC;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
                padding: 8px 18px;
                min-height: 38px;
            }
            QPushButton:hover {
                background-color: #DDF5F8;
            }
            QPushButton:pressed {
                background-color: #CDEEF3;
            }
            """
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        title = QLabel(title_text)
        title.setStyleSheet("font-size: 16px; font-weight: 800; color: #163047;")

        text_box = QTextBrowser()
        text_box.setOpenExternalLinks(False)
        text_box.setReadOnly(True)
        text_box.setHtml(details_html)
        text_box.setStyleSheet(
            text_box.styleSheet()
            + "QScrollBar:vertical { width: 12px; }"
        )

        close_button = QPushButton(_("buttons.close"))
        close_button.clicked.connect(dialog.accept)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(close_button)

        layout.addWidget(title)
        layout.addWidget(text_box, 1)
        layout.addLayout(button_row)

        dialog.exec()

    def _run_chat_transfer(self):
        try:
            LOGGER.info("Starting chat transfer for config: %s", self.config_path)
            self.save_form_to_toml()
        except Exception as error:
            LOGGER.exception("Failed to save config before chat transfer: %s", self.config_path)
            QMessageBox.warning(
                self,
                _("dialogs.save_error"),
                f"{_('dialogs.save_error_msg', error=error)}",
            )
            return

        dialog = ChatTransferProgressDialog(self)
        dialog.setWindowTitle(_("progress.title"))
        dialog.setWindowIcon(QIcon(get_resource_path("assets/icon.png")))
        dialog.setModal(True)
        dialog.resize(820, 560)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: #FFFFFF;
            }
            QLabel {
                color: #163047;
                background: transparent;
            }
            QProgressBar {
                border: 1px solid #D7E9EE;
                border-radius: 8px;
                background: #F3F7F9;
                text-align: center;
                color: #163047;
                min-height: 20px;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background-color: #3BB4C8;
                border-radius: 7px;
            }
            QTextBrowser {
                background-color: #FFFFFF;
                color: #163047;
                border: 1px solid #D7E9EE;
                border-radius: 12px;
                padding: 6px;
                font-size: 13px;
            }
            QPushButton {
                background-color: #EAF8FB;
                color: #3097A6;
                border: 1px solid #B9E5EC;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
                padding: 8px 18px;
                min-height: 38px;
            }
            QPushButton:hover {
                background-color: #DDF5F8;
            }
            QPushButton:pressed {
                background-color: #CDEEF3;
            }
            QPushButton:disabled {
                background-color: #F3F7F9;
                color: #8AA1AF;
                border: 1px solid #D7E9EE;
            }
            """
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel(_("progress.title"))
        title.setStyleSheet("font-size: 16px; font-weight: 800; color: #163047;")

        status_label = QLabel(_("progress.preparing"))
        status_label.setStyleSheet("font-size: 13px; color: #5E7486;")

        counter_label = QLabel(_("progress.messages", current=0, total=0))
        counter_label.setStyleSheet("font-size: 13px; color: #163047; font-weight: 600;")

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 0)
        progress_bar.setValue(0)

        log_title = QLabel(_("progress.events"))
        log_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #163047;")

        log_browser = QTextBrowser()
        log_browser.setReadOnly(True)

        cancel_button = QPushButton(_("buttons.cancel"))

        layout.addWidget(title)
        layout.addWidget(status_label)
        layout.addWidget(counter_label)
        layout.addWidget(progress_bar)
        layout.addWidget(log_title)
        layout.addWidget(log_browser, 1)
        layout.addWidget(cancel_button, 0, Qt.AlignmentFlag.AlignRight)

        thread = QThread(self)
        worker = ChatTransferWorker(self.config_path)
        worker.moveToThread(thread)

        state = {
            "result": None,
            "error": None,
            "canceled": False,
        }

        def append_log_line(text: str):
            if not text:
                return
            log_browser.append(text.replace("<", "&lt;").replace(">", "&gt;"))

        def on_progress(current: int, total: int):
            if total > 0:
                progress_bar.setRange(0, total)
                progress_bar.setValue(current)
                counter_label.setText(_("progress.messages", current=current, total=total))
                status_label.setText(_("progress.transferring"))

        def request_cancel():
            status_label.setText(_("progress.stopping"))
            cancel_button.setEnabled(False)
            worker.cancel()

        def on_finished(result):
            state["result"] = result
            dialog.allow_close()
            dialog.accept()

        def on_failed(error_text: str):
            state["error"] = error_text
            dialog.allow_close()
            dialog.reject()

        def on_canceled():
            state["canceled"] = True
            dialog.allow_close()
            dialog.reject()

        thread.started.connect(worker.run)
        worker.progress_changed.connect(on_progress)
        worker.log_message.connect(append_log_line)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        worker.canceled.connect(on_canceled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.canceled.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.canceled.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        cancel_button.clicked.connect(request_cancel)
        dialog.cancel_requested.connect(request_cancel)

        thread.start()
        dialog.show()
        QApplication.processEvents()
        dialog.exec()

        if state["canceled"]:
            LOGGER.info("Chat transfer canceled for config: %s", self.config_path)
            QMessageBox.information(
                self,
                _("dialogs.transfer_stopped"),
                _("dialogs.transfer_stopped_msg"),
            )
            return

        if state["error"]:
            LOGGER.error("Chat transfer failed for config %s: %s", self.config_path, state["error"])
            QMessageBox.warning(
                self,
                _("dialogs.transfer_error"),
                f"{_('dialogs.transfer_error_msg', error=state['error'])}",
            )
            return

        result = state["result"] or {}
        chat_name = result.get("chat_name", "") if isinstance(result, dict) else ""
        chat_type = result.get("chat_type", "") if isinstance(result, dict) else ""
        chat_id = result.get("chat_id", "") if isinstance(result, dict) else ""

        lines = [_("results.success")]
        if chat_name:
            lines.append(_("results.chat_name", name=chat_name))
        if chat_type:
            lines.append(_("results.chat_type", type=chat_type))
        if chat_id:
            lines.append(_("results.chat_id", id=chat_id))

        LOGGER.info("Chat transfer completed successfully for config: %s", self.config_path)
        QMessageBox.information(
            self,
            _("dialogs.transfer_complete"),
            "\n".join(lines),
        )

    def _create_card(self, object_name: str) -> QFrame:
        card = QFrame()
        card.setObjectName(object_name)
        card.setStyleSheet(
            f"""
            QFrame#{object_name} {{
                background-color: #FFFFFF;
                border: 1px solid #E2EEF2;
                border-radius: 22px;
            }}
            """
        )
        return card

    def _create_section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            "font-size: 16px; font-weight: 800; color: #163047; background: transparent;"
        )
        return label

    def _create_hint_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(
            "font-size: 13px; color: #5E7486; background: transparent;"
        )
        return label

    def _create_inline_warning_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(False)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        label.setStyleSheet(
            "font-size: 10px; color: #F67A1E; background: transparent;"
        )
        label.hide()
        return label

    def _create_info_button(self, tooltip_text: str | None = None) -> QToolButton:
        if tooltip_text is None:
            tooltip_text = _("tooltips.show_hint")
        button = QToolButton()
        button.setText("i")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tooltip_text)
        button.setFixedSize(18, 18)
        button.setStyleSheet(
            """
            QToolButton {
                background-color: #EAF8FB;
                color: #3097A6;
                border: 1px solid #B9E5EC;
                border-radius: 9px;
                font-size: 11px;
                font-weight: 700;
                padding: 0;
            }
            QToolButton:hover {
                background-color: #DDF5F8;
                border: 1px solid #3BB4C8;
                color: #163047;
            }
            """
        )
        return button

    def _show_users_info_popup(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(_("table_info.title"))
        dialog.setWindowIcon(QIcon(get_resource_path("assets/icon.png")))
        dialog.setModal(True)
        dialog.setMinimumWidth(640)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: #FFFFFF;
            }
            QLabel {
                color: #163047;
                font-size: 13px;
                background: transparent;
            }
            QPushButton {
                background-color: #EAF8FB;
                color: #3097A6;
                border: 1px solid #B9E5EC;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
                padding: 8px 18px;
                min-height: 38px;
            }
            QPushButton:hover {
                background-color: #DDF5F8;
            }
            QPushButton:pressed {
                background-color: #CDEEF3;
            }
            """
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        title = QLabel(_("table_info.title_full"))
        title.setStyleSheet("font-size: 16px; font-weight: 800; color: #163047;")

        text = QLabel(_("table_info.description"))
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setOpenExternalLinks(True)
        text.setStyleSheet("font-size: 13px; color: #5E7486; line-height: 1.4;")

        close_button = QPushButton(_("buttons.understand"))
        close_button.clicked.connect(dialog.accept)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(close_button)

        layout.addWidget(title)
        layout.addWidget(text)
        layout.addLayout(button_row)

        dialog.exec()

    def _create_primary_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(46)
        button.setStyleSheet(
            """
            QPushButton {
                background-color: #3BB4C8;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 15px;
                font-weight: 700;
                padding: 0 20px;
            }
            QPushButton:hover {
                background-color: #41C2E1;
            }
            QPushButton:pressed {
                background-color: #3097A6;
            }
            QPushButton:disabled {
                background-color: #D7E9EE;
                color: #8AA1AF;
                border: 1px solid #C7DCE3;
            }
            """
        )
        return button

    def _create_icon_button(self, tooltip_text: str, icon_name: str) -> QPushButton:
        button = QPushButton()
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tooltip_text)
        button.setFixedSize(46, 46)
        button.setIcon(qta.icon(icon_name, color="#3097A6"))
        button.setIconSize(QSize(18, 18))
        button.setStyleSheet(
            """
            QPushButton {
                background-color: #EAF8FB;
                color: #3097A6;
                border: 1px solid #B9E5EC;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: #DDF5F8;
            }
            QPushButton:pressed {
                background-color: #CDEEF3;
            }
            QPushButton:disabled {
                background-color: #F3F7F9;
                color: #8AA1AF;
                border: 1px solid #D7E9EE;
            }
            """
        )
        return button

    def _create_secondary_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(46)
        button.setStyleSheet(
            """
            QPushButton {
                background-color: #EAF8FB;
                color: #3097A6;
                border: 1px solid #B9E5EC;
                border-radius: 12px;
                font-size: 15px;
                font-weight: 700;
                padding: 0 20px;
            }
            QPushButton:hover {
                background-color: #DDF5F8;
            }
            QPushButton:pressed {
                background-color: #CDEEF3;
            }
            QPushButton:disabled {
                background-color: #F3F7F9;
                color: #8AA1AF;
                border: 1px solid #D7E9EE;
            }
            """
        )
        return button

    def _browse_cover_image(self):
        file_path, _filter = QFileDialog.getOpenFileName(
            self,
            _("tooltips.select_cover"),
            self.cover_input.text(),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if file_path:
            self.cover_input.setText(file_path)

    def _update_voice_controls_state(self, checked: bool):
        self.cover_input.setEnabled(checked)
        self.cover_browse_button.setEnabled(checked)

    def _update_datetime_controls_state(self, checked: bool):
        self.timezone_combo.setEnabled(checked)
        self.caption_input.setEnabled(checked)

    def _update_supergroup_template_state(self, chat_type: str):
        is_supergroup = chat_type == "supergroup"
        self.supergroup_template_label.setEnabled(is_supergroup)
        self.supergroup_template_input.setEnabled(is_supergroup)

    def _update_telegram_bot_controls_state(self, checked: bool):
        self.telegram_bot_token_input.setEnabled(checked)
        self.telegram_bot_chat_id_input.setEnabled(checked)

    def _apply_settings(self):
        try:
            self.save_form_to_toml()
            self._is_loading_toml = True
            self.reload_from_toml()
            self._is_loading_toml = False
            self.run_button.setEnabled(True)
        except Exception as error:
            self._is_loading_toml = False
            QMessageBox.warning(
                self,
                _("dialogs.save_error"),
                f"{_('dialogs.save_error_msg', error=error)}",
            )

    def _apply_input_style(self, widget):
        widget.setStyleSheet(
            """
            QLineEdit, QComboBox {
                background-color: #FFFFFF;
                color: #163047;
                border: 1px solid #D7E9EE;
                border-radius: 10px;
                padding: 0 12px;
                min-height: 42px;
                font-size: 14px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #3BB4C8;
            }
            QLineEdit:disabled, QComboBox:disabled {
                background-color: #F3F7F9;
                color: #8AA1AF;
                border: 1px solid #D7E9EE;
            }
            QMenu {
                background-color: #FFFFFF;
                color: #163047;
                border: 1px solid #D7E9EE;
                padding: 4px;
            }
            QMenu::item {
                padding: 4px 20px;
            }
            QMenu::item:selected {
                background-color: #EAF8FB;
                color: #163047;
            }
            QMenu::item:disabled {
                color: #8AA1AF;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            """
        )

    def _apply_checkbox_style(self, checkbox: QCheckBox):
        checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                font-weight: 400;
                color: #163047;
                spacing: 10px;
                background: transparent;
            }
            """
        )

    def _apply_spinbox_style(self, widget: QSpinBox):
        widget.setStyleSheet(
            """
            QSpinBox {
                background-color: #FFFFFF;
                color: #163047;
                border: 1px solid #D7E9EE;
                border-radius: 10px;
                padding: 0 12px;
                min-height: 42px;
                font-size: 14px;
            }
            QSpinBox:focus {
                border: 1px solid #3BB4C8;
            }
            QSpinBox:disabled {
                background-color: #F3F7F9;
                color: #8AA1AF;
                border: 1px solid #D7E9EE;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 20px;
                border: none;
                background: transparent;
            }
            QMenu {
                background-color: #FFFFFF;
                color: #163047;
                border: 1px solid #D7E9EE;
                padding: 4px;
            }
            QMenu::item {
                padding: 4px 20px;
            }
            QMenu::item:selected {
                background-color: #EAF8FB;
                color: #163047;
            }
            QMenu::item:disabled {
                color: #8AA1AF;
            }
            """
        )

    def _get_available_timezones(self) -> list[str]:
        return sorted(bytes(tz).decode("utf-8") for tz in QTimeZone.availableTimeZoneIds())

    def _build_ui(self):
        self.setStyleSheet("background-color: #F6FAFC;")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 14, 20, 14)
        root_layout.setSpacing(10)

        settings_shell = QFrame()
        settings_shell.setObjectName("settingsShell")
        settings_shell.setStyleSheet(
            """
            QFrame#settingsShell {
                background-color: #FFFFFF;
                border: 1px solid #E2EEF2;
                border-radius: 22px;
            }
            """
        )

        shell_layout = QVBoxLayout(settings_shell)
        shell_layout.setContentsMargins(14, 14, 14, 16)
        shell_layout.setSpacing(10)

        header_card = QFrame()
        header_card.setObjectName("settingsHeaderCard")
        header_card.setStyleSheet(
            """
            QFrame#settingsHeaderCard {
                background: transparent;
                border: none;
            }
            """
        )
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(2, 0, 2, 0)
        header_layout.setSpacing(4)

        title = QLabel(_("settings.title"))
        title.setStyleSheet(
            "font-size: 20px; font-weight: 800; color: #163047; background: transparent;"
        )

        source_badge = QLabel(_("settings.source_badge", path=self.folder_path, config=self.config_path))
        source_badge.setWordWrap(False)
        source_badge.setMinimumWidth(520)
        source_badge.setMaximumWidth(1180-100)
        source_badge.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        source_badge.setStyleSheet(
            """
            QLabel {
                background-color: #EAF8FB;
                color: #3097A6;
                border: 1px solid #B9E5EC;
                border-radius: 10px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 600;
            }
            """
        )

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title_row.addSpacing(4)
        title_row.addWidget(source_badge, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        
        header_layout.addLayout(title_row)

        media_card = self._create_card("mediaCard")
        media_layout = QVBoxLayout(media_card)
        media_layout.setContentsMargins(18, 16, 18, 16)
        media_layout.setSpacing(8)
        media_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        media_title = self._create_section_title(_("media.title"))

        self.voice_checkbox = QCheckBox(_("media.voice_to_video"))
        self._apply_checkbox_style(self.voice_checkbox)
        self.voice_checkbox.setChecked(False)

        self.voice_info_label = self._create_inline_warning_label(
            _("media.ffmpeg_warning")
        )

        cover_label = self._create_hint_label(_("media.cover_label"))
        self.cover_input = QLineEdit("cover/ru.png")
        self._apply_input_style(self.cover_input)
        self.cover_browse_button = self._create_secondary_button("")
        self.cover_browse_button.setToolTip(_("buttons.select_file"))
        self.cover_browse_button.setFixedSize(42, 42)
        self.cover_browse_button.setIcon(qta.icon("fa5s.folder-open", color="#3097A6"))
        self.cover_browse_button.setIconSize(QSize(16, 16))
        self.cover_browse_button.clicked.connect(self._browse_cover_image)

        self.stickers_checkbox = QCheckBox(_("media.stickers"))
        self._apply_checkbox_style(self.stickers_checkbox)
        self.stickers_checkbox.setChecked(False)

        self.stickers_info_label = self._create_inline_warning_label(
            _("media.cairo_warning")
        )
        self.stickers_info_label.setWordWrap(True)
        self.stickers_info_label.setFixedHeight(28)

        self.datetime_checkbox = QCheckBox(_("media.datetime"))
        self._apply_checkbox_style(self.datetime_checkbox)
        self.datetime_checkbox.setChecked(False)
        self.datetime_checkbox.toggled.connect(self._update_datetime_controls_state)

        self.voice_checkbox.toggled.connect(self.voice_info_label.setVisible)
        self.voice_checkbox.toggled.connect(self._update_voice_controls_state)
        self.stickers_checkbox.toggled.connect(self.stickers_info_label.setVisible)

        self._update_voice_controls_state(self.voice_checkbox.isChecked())

        self.timezone_combo = ElidedComboBox()
        self.timezone_combo.setEditable(False)
        for tz in self._get_available_timezones():
            self.timezone_combo.addItem(tz)
            idx = self.timezone_combo.count() - 1
            self.timezone_combo.setItemData(idx, tz, Qt.ItemDataRole.UserRole)

        self._apply_input_style(self.timezone_combo)
        self.timezone_combo.setFixedWidth(130)
        self.timezone_combo.setCurrentIndex(self.timezone_combo.findText("GMT"))
        self.timezone_combo.setToolTip(
            self.timezone_combo.currentData(Qt.ItemDataRole.UserRole)
            or self.timezone_combo.currentText()
        )
        self.timezone_combo.currentIndexChanged.connect(
            lambda _=None: self.timezone_combo.setToolTip(
                self.timezone_combo.currentData(Qt.ItemDataRole.UserRole)
                or self.timezone_combo.currentText()
            )
        )

        self.caption_input = QLineEdit(_("media.caption_default"))
        self._apply_input_style(self.caption_input)
        self.caption_input.setPlaceholderText(_("media.caption_placeholder"))
        self._update_datetime_controls_state(self.datetime_checkbox.isChecked())

        voice_column = QVBoxLayout()
        voice_column.setSpacing(4)
        voice_column.setAlignment(Qt.AlignmentFlag.AlignTop)

        voice_header_row = QHBoxLayout()
        voice_header_row.setContentsMargins(0, 0, 0, 0)
        voice_header_row.setSpacing(6)
        voice_header_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        voice_header_row.addWidget(self.voice_checkbox, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        voice_header_row.addStretch()

        cover_row = QHBoxLayout()
        cover_row.setSpacing(8)
        cover_row.addWidget(self.cover_input, 1)
        cover_row.addWidget(self.cover_browse_button, 0)

        self.voice_info_label.setFixedHeight(16)
        voice_column.addLayout(voice_header_row)
        voice_column.addWidget(self.voice_info_label, 0, Qt.AlignmentFlag.AlignLeft)
        voice_column.addWidget(cover_label)
        voice_column.addLayout(cover_row)

        stickers_column = QVBoxLayout()
        stickers_column.setContentsMargins(12, 0, 0, 0)
        stickers_column.setSpacing(4)
        stickers_column.setAlignment(Qt.AlignmentFlag.AlignTop)

        stickers_header_row = QHBoxLayout()
        stickers_header_row.setContentsMargins(0, 0, 0, 0)
        stickers_header_row.setSpacing(6)
        stickers_header_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        stickers_header_row.addWidget(self.stickers_checkbox, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        stickers_header_row.addStretch()

        stickers_note = self._create_hint_label(_("media.stickers_note"))

        stickers_column.addLayout(stickers_header_row)
        stickers_column.addWidget(self.stickers_info_label, 0, Qt.AlignmentFlag.AlignLeft)
        stickers_column.addWidget(stickers_note)
        stickers_column.addStretch()

        datetime_column = QVBoxLayout()
        datetime_column.setSpacing(4)
        datetime_label = self._create_hint_label(_("media.datetime_label"))

        datetime_column.addWidget(self.datetime_checkbox)
        datetime_column.addWidget(datetime_label)

        datetime_row = QHBoxLayout()
        datetime_row.setSpacing(8)
        datetime_row.addWidget(self.timezone_combo, 0)
        datetime_row.addWidget(self.caption_input, 1)

        datetime_column.addLayout(datetime_row)
        datetime_column.addStretch()

        media_grid_row = QHBoxLayout()
        media_grid_row.setSpacing(10)
        media_grid_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        media_grid_row.addLayout(voice_column, 4)
        media_grid_row.addLayout(stickers_column, 3)
        media_grid_row.addLayout(datetime_column, 4)

        media_layout.addWidget(media_title)
        media_layout.addSpacing(2)
        media_layout.addLayout(media_grid_row)

        chat_card = self._create_card("chatCard")
        chat_layout = QVBoxLayout(chat_card)
        chat_layout.setContentsMargins(18, 16, 18, 16)
        chat_layout.setSpacing(8)
        chat_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        chat_title = self._create_section_title(_("chat.title"))

        name_label = self._create_hint_label(_("chat.name_label"))
        self.chat_name_input = QLineEdit()
        self._apply_input_style(self.chat_name_input)
        self.chat_name_input.setPlaceholderText(_("chat.name_placeholder"))

        owner_label = self._create_hint_label(_("chat.owner_label"))
        self.owner_input = QLineEdit()
        self._apply_input_style(self.owner_input)
        self.owner_input.setPlaceholderText(_("chat.owner_placeholder"))

        type_label = self._create_hint_label(_("chat.type_label"))
        self.chat_type_combo = QComboBox()
        self.chat_type_combo.addItem(_("chat.type_personal"), "personal")
        self.chat_type_combo.addItem(_("chat.type_group"), "group")
        self.chat_type_combo.addItem(_("chat.type_channel"), "channel")
        self.chat_type_combo.addItem(_("chat.type_supergroup"), "supergroup")
        self._apply_input_style(self.chat_type_combo)

        self.supergroup_template_label = self._create_hint_label(_("chat.template_label"))
        self.supergroup_template_input = QLineEdit("{topic} | {supergroup}")
        self._apply_input_style(self.supergroup_template_input)

        first_row = QHBoxLayout()
        first_row.setSpacing(10)
        first_row.setAlignment(Qt.AlignmentFlag.AlignTop)

        name_column = QVBoxLayout()
        name_column.setSpacing(4)
        name_column.addWidget(name_label)
        name_column.addWidget(self.chat_name_input)

        owner_column = QVBoxLayout()
        owner_column.setSpacing(4)
        owner_column.addWidget(owner_label)
        owner_column.addWidget(self.owner_input)

        type_column = QVBoxLayout()
        type_column.setSpacing(4)
        type_column.addWidget(type_label)
        type_column.addWidget(self.chat_type_combo)

        template_column = QVBoxLayout()
        template_column.setSpacing(4)
        template_column.addWidget(self.supergroup_template_label)
        template_column.addWidget(self.supergroup_template_input)

        first_row.addLayout(name_column, 3)
        first_row.addLayout(owner_column, 2)
        first_row.addLayout(type_column, 2)
        first_row.addLayout(template_column, 3)

        self.chat_type_combo.currentIndexChanged.connect(
            lambda _=None: self._update_supergroup_template_state(
                str(self.chat_type_combo.currentData() or "")
            )
        )
        self._update_supergroup_template_state(str(self.chat_type_combo.currentData() or ""))

        chat_layout.addWidget(chat_title)
        chat_layout.addSpacing(2)
        chat_layout.addLayout(first_row)

        telegram_bot_card = self._create_card("telegramBotCard")
        telegram_bot_layout = QVBoxLayout(telegram_bot_card)
        telegram_bot_layout.setContentsMargins(18, 16, 18, 16)
        telegram_bot_layout.setSpacing(8)

        telegram_bot_title = self._create_section_title(_("telegram_bot.title"))

        telegram_bot_row = QHBoxLayout()
        telegram_bot_row.setSpacing(10)
        telegram_bot_row.setAlignment(Qt.AlignmentFlag.AlignTop)

        bot_token_column = QVBoxLayout()
        bot_token_column.setSpacing(4)
        bot_token_label = self._create_hint_label(_("telegram_bot.token_label"))
        self.telegram_bot_token_input = QLineEdit()
        self._apply_input_style(self.telegram_bot_token_input)
        self.telegram_bot_token_input.setPlaceholderText(_("telegram_bot.token_placeholder"))
        bot_token_column.addWidget(bot_token_label)
        bot_token_column.addWidget(self.telegram_bot_token_input)

        bot_chat_id_column = QVBoxLayout()
        bot_chat_id_column.setSpacing(4)
        bot_chat_id_label = self._create_hint_label(_("telegram_bot.chat_id_label"))
        self.telegram_bot_chat_id_input = QLineEdit()
        self._apply_input_style(self.telegram_bot_chat_id_input)
        self.telegram_bot_chat_id_input.setPlaceholderText(_("telegram_bot.chat_id_placeholder"))
        bot_chat_id_column.addWidget(bot_chat_id_label)
        bot_chat_id_column.addWidget(self.telegram_bot_chat_id_input)

        telegram_bot_row.addLayout(bot_token_column, 3)
        telegram_bot_row.addLayout(bot_chat_id_column, 2)

        self.telegram_bot_enrich_checkbox = QCheckBox(_("telegram_bot.enrich"))
        self._apply_checkbox_style(self.telegram_bot_enrich_checkbox)

        self.telegram_bot_enrich_hint = QLabel(
            _("telegram_bot.enrich_hint")
        )
        self.telegram_bot_enrich_hint.setWordWrap(True)
        self.telegram_bot_enrich_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.telegram_bot_enrich_hint.setStyleSheet(
            "font-size: 11px; color: #F67A1E; background: transparent;"
        )
        self.telegram_bot_enrich_hint.hide()
        self.telegram_bot_enrich_checkbox.toggled.connect(self.telegram_bot_enrich_hint.setVisible)
        self.telegram_bot_enrich_checkbox.toggled.connect(self._update_telegram_bot_controls_state)

        telegram_bot_options = QVBoxLayout()
        telegram_bot_options.setContentsMargins(0, 2, 0, 0)
        telegram_bot_options.setSpacing(4)
        telegram_bot_options.addWidget(self.telegram_bot_enrich_checkbox, 0, Qt.AlignmentFlag.AlignLeft)

        telegram_bot_layout.addWidget(telegram_bot_title)
        telegram_bot_layout.addSpacing(2)
        telegram_bot_layout.addLayout(telegram_bot_options)
        telegram_bot_layout.addLayout(telegram_bot_row)
        telegram_bot_layout.addWidget(self.telegram_bot_enrich_hint)
        self._update_telegram_bot_controls_state(self.telegram_bot_enrich_checkbox.isChecked())

        users_card = self._create_card("usersCard")
        users_layout = QVBoxLayout(users_card)
        users_layout.setContentsMargins(18, 16, 18, 16)
        users_layout.setSpacing(10)

        users_title = self._create_section_title(_("users.title"))
        self.users_info_button = self._create_info_button(_("table_info.title"))
        self.users_info_button.clicked.connect(self._show_users_info_popup)

        users_header_row = QHBoxLayout()
        users_header_row.setSpacing(16)
        users_header_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        users_text_column = QVBoxLayout()
        users_text_column.setSpacing(4)

        users_title_row = QHBoxLayout()
        users_title_row.setContentsMargins(0, 0, 0, 0)
        users_title_row.setSpacing(6)
        users_title_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        users_title_row.addWidget(users_title, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        users_title_row.addWidget(self.users_info_button, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        users_title_row.addStretch(1)

        users_text_column.addLayout(users_title_row)

        users_controls_row = QHBoxLayout()
        users_controls_row.setContentsMargins(0, 0, 0, 0)
        users_controls_row.setSpacing(10)
        users_controls_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        password_column = QVBoxLayout()
        password_column.setContentsMargins(0, 6, 0, 0)
        password_column.setSpacing(0)
        password_column.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        password_row = QHBoxLayout()
        password_row.setContentsMargins(0, 0, 0, 0)
        password_row.setSpacing(8)
        password_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        password_label = self._create_hint_label(_("users.password_label"))
        password_label.setWordWrap(False)
        self.registration_password_input = QLineEdit()
        self._apply_input_style(self.registration_password_input)
        self.registration_password_input.setPlaceholderText(_("users.password_placeholder"))
        self.registration_password_input.setFixedWidth(150)
        self.registration_password_input.setFixedHeight(30)
        self.registration_password_input.setStyleSheet(
            self.registration_password_input.styleSheet()
            + "QLineEdit { min-height: 30px; font-size: 12px; padding: 0 10px; }"
        )
        self.registration_password_input.textChanged.connect(self._apply_registration_password_to_table)
        email_domain_label = self._create_hint_label(_("users.email_domain_label"))
        email_domain_label.setWordWrap(False)

        self.registration_email_domain_input = QLineEdit()
        self._apply_input_style(self.registration_email_domain_input)
        self.registration_email_domain_input.setPlaceholderText("example.com")
        self.registration_email_domain_input.setToolTip(self.EMAIL_DOMAIN_TOOLTIP)
        self.registration_email_domain_input.setFixedWidth(112)
        self.registration_email_domain_input.setFixedHeight(30)
        self.registration_email_domain_input.setStyleSheet(
            self.registration_email_domain_input.styleSheet()
            + "QLineEdit { min-height: 30px; font-size: 12px; padding: 0 10px; }"
        )


        password_row.addWidget(password_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        password_row.addWidget(self.registration_password_input, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        password_row.addSpacing(8)
        password_row.addWidget(email_domain_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        password_row.addWidget(self.registration_email_domain_input, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        password_row.addStretch(1)

        password_column.addLayout(password_row)

        users_controls_row.addLayout(password_column)

        user_actions_layout = QHBoxLayout()
        user_actions_layout.setSpacing(8)
        user_actions_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        self.parse_users_button = self._create_icon_button(
            _("users.refresh_tooltip"),
            "fa5s.sync-alt",
        )
        self.add_users_button = self._create_icon_button(
            _("users.register_tooltip"),
            "fa5s.user-plus",
        )
        self.add_users_button.setEnabled(False)
        self.parse_users_button.clicked.connect(self._refresh_users)
        self.add_users_button.clicked.connect(self._add_users_to_server)

        user_actions_layout.addWidget(self.parse_users_button)
        user_actions_layout.addWidget(self.add_users_button)

        users_header_row.addLayout(users_text_column, 0)
        users_header_row.addSpacing(10)
        users_header_row.addLayout(users_controls_row, 0)
        users_header_row.addStretch(1)
        users_header_row.addLayout(user_actions_layout, 0)

        self.users_table = ResizableTable(0, 7)
        self.users_table.setHorizontalHeader(MutedHeaderView(Qt.Orientation.Horizontal, self.users_table))
        self.users_table.setHorizontalHeaderLabels(
            [
                _("users.headers.telegram_id"),
                _("users.headers.trueconf_id"),
                _("users.headers.token"),
                _("users.headers.password"),
                _("users.headers.display_name"),
                _("users.headers.real_name"),
                _("users.headers.username"),
            ]
        )
        self.users_table.verticalHeader().setVisible(False)
        self.users_table.setAlternatingRowColors(False)
        self.users_table.setShowGrid(True)
        self.users_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.users_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.SelectedClicked
        )
        self.users_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.users_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.users_table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.users_table.setWordWrap(False)
        self.users_table.setMinimumHeight(520)
        self.users_table.setStyleSheet(
            """
            QTableWidget {
                background-color: #FFFFFF;
                border: 1px solid #E2EEF2;
                border-radius: 5px;
                color: #163047;
                font-size: 13px;
                gridline-color: #E2EEF2;
            }
            QHeaderView::section {
                background-color: #EAF8FB;
                color: #3097A6;
                border: none;
                border-bottom: 1px solid #D7E9EE;
                border-right: 1px solid #D7E9EE;
                padding: 10px;
                font-size: 12px;
                font-weight: 700;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #EEF5F7;
            }
            QTableWidget::item:selected {
                background-color: #EAF8FB;
                color: #163047;
            }
            QTableWidget QLineEdit {
                background-color: #FFFFFF;
                color: #163047;
                border: 1px solid #3BB4C8;
                border-radius: 8px;
                padding: 4px 8px;
                min-height: 30px;
                selection-background-color: #3BB4C8;
                selection-color: #FFFFFF;
            }
            """
        )
        self._is_resizing_columns = False
        self._col_min_widths = [140, 165, 140, 100, 205, 170, 180]
        self._col_ratios = [w / sum(self._col_min_widths) for w in self._col_min_widths]

        self.users_table.setColumnWidth(0, 140)  # Telegram ID
        self.users_table.setColumnWidth(1, 165)  # TrueConf ID
        self.users_table.setColumnWidth(2, 140)  # Токен
        self.users_table.setColumnWidth(3, 100)  # Пароль
        self.users_table.setColumnWidth(4, 180)  # Отобр. имя
        self.users_table.setColumnWidth(5, 170)  # Имя в Telegram
        self.users_table.setColumnWidth(6, 180)  # Юзернейм (@)

        self.users_table.horizontalHeader().sectionResized.connect(self._on_user_table_section_resized)
        QTimer.singleShot(0, self._resize_user_table_columns)

        users_layout.addLayout(users_header_row)


        users_layout.addWidget(self.users_table)

        footer_card = self._create_card("footerCard")
        footer_layout = QHBoxLayout(footer_card)
        footer_layout.setContentsMargins(18, 12, 18, 12)
        footer_layout.setSpacing(10)

        self.back_button = self._create_secondary_button(_("buttons.back"))
        self.save_button = self._create_secondary_button(_("buttons.apply"))
        self.save_button.setToolTip(_("buttons.apply_tooltip"))
        self.run_button = self._create_primary_button(_("buttons.run"))
        self.run_button.setEnabled(False)
        self.back_button.clicked.connect(self.on_back)
        self.save_button.clicked.connect(self._apply_settings)
        self.run_button.clicked.connect(self._run_chat_transfer)

        footer_layout.addWidget(self.back_button)
        footer_layout.addStretch()
        footer_layout.addWidget(self.save_button)
        footer_layout.addWidget(self.run_button)

        self.users_table.setMinimumHeight(520)

        self.tabs = QTabWidget()
        self.tabs.setContentsMargins(0, 8, 0, 4)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setDocumentMode(False)
        self.tabs.setAutoFillBackground(False)
        self.tabs.setStyleSheet(
            """
            QTabWidget {
                background: transparent;
            }
            QTabWidget::pane {
                border: none;
                background: transparent;
                margin-top: 0px;
                padding: 0px;
                padding-top: 4px;
            }
            QTabBar {
                background: transparent;
                left: 2px;
            }
            QTabBar::tab {
                background: transparent;
                color: #3097A6;
                border: none;
                padding: 6px 12px;
                margin-right: 6px;
                font-size: 13px;
                font-weight: 700;
                border-radius: 10px;
            }
            QTabBar::tab:selected {
                background: #EAF8FB;
                color: #163047;
            }
            QTabBar::tab:!selected:hover {
                background: #F3FBFD;
                color: #163047;
            }
            """
        )

        server_tab = QWidget()
        server_tab.setStyleSheet("background: transparent;")
        server_tab_layout = QVBoxLayout(server_tab)
        server_tab_layout.setContentsMargins(0, 0, 0, 0)
        server_tab_layout.setSpacing(10)

        server_card = self._create_card("serverCard")
        server_layout = QVBoxLayout(server_card)
        server_layout.setContentsMargins(18, 16, 18, 16)
        server_layout.setSpacing(8)

        server_title = self._create_section_title(_("server.title"))

        server_grid = QHBoxLayout()
        server_grid.setSpacing(10)
        server_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        address_column = QVBoxLayout()
        address_column.setSpacing(4)
        address_column.setAlignment(Qt.AlignmentFlag.AlignTop)
        address_label = self._create_hint_label(_("server.address_label"))
        self.server_address_input = QLineEdit()
        self._apply_input_style(self.server_address_input)
        self.server_address_input.setPlaceholderText(_("server.address_placeholder"))
        address_column.addWidget(address_label)
        address_column.addWidget(self.server_address_input)
        address_column.addStretch()

        port_column = QVBoxLayout()
        port_column.setSpacing(4)
        port_column.setAlignment(Qt.AlignmentFlag.AlignTop)
        port_label = self._create_hint_label(_("server.port_label"))
        self.server_port_input = QSpinBox()
        self.server_port_input.setRange(1, 65535)
        self.server_port_input.setValue(443)
        self._apply_spinbox_style(self.server_port_input)
        port_column.addWidget(port_label)
        port_column.addWidget(self.server_port_input)
        port_column.addStretch()

        ssl_column = QVBoxLayout()
        ssl_column.setSpacing(4)
        ssl_column.setAlignment(Qt.AlignmentFlag.AlignTop)
        ssl_label = self._create_hint_label(_("server.ssl_label"))
        self.server_verify_ssl_combo = QComboBox()
        self.server_verify_ssl_combo.addItems([_("server.ssl_off"), _("server.ssl_on")])
        self._apply_input_style(self.server_verify_ssl_combo)
        ssl_column.addWidget(ssl_label)
        ssl_column.addWidget(self.server_verify_ssl_combo)
        ssl_column.addStretch()

        token_column = QVBoxLayout()
        token_column.setSpacing(4)
        token_column.setAlignment(Qt.AlignmentFlag.AlignTop)
        token_label = self._create_hint_label(_("server.token_label"))
        self.server_access_token_input = QLineEdit()
        self._apply_input_style(self.server_access_token_input)
        self.server_access_token_input.setPlaceholderText(_("server.token_placeholder"))
        token_column.addWidget(token_label)
        token_column.addWidget(self.server_access_token_input)
        token_column.addStretch()

        server_grid.addLayout(address_column, 3)
        server_grid.addLayout(port_column, 1)
        server_grid.addLayout(ssl_column, 2)
        server_grid.addLayout(token_column, 4)
        server_grid.setStretch(0, 3)
        server_grid.setStretch(1, 1)
        server_grid.setStretch(2, 2)
        server_grid.setStretch(3, 4)

        server_layout.addWidget(server_title)
        server_layout.addSpacing(2)
        server_layout.addLayout(server_grid)
        server_tab_layout.addWidget(server_card)

        chat_tab = QWidget()
        chat_tab.setStyleSheet("background: transparent;")
        chat_tab_layout = QVBoxLayout(chat_tab)
        chat_tab_layout.setContentsMargins(0, 0, 0, 0)
        chat_tab_layout.setSpacing(10)
        chat_tab_layout.addWidget(chat_card)
        chat_tab_layout.addWidget(media_card)
        chat_tab_layout.addStretch()

        server_tab_layout.addWidget(telegram_bot_card)
        server_tab_layout.addStretch()

        users_tab = QWidget()
        users_tab.setStyleSheet("background: transparent;")
        users_tab_layout = QVBoxLayout(users_tab)
        users_tab_layout.setContentsMargins(0, 0, 0, 0)
        users_tab_layout.setSpacing(10)
        users_tab_layout.addWidget(users_card)

        self.tabs.addTab(server_tab, _("settings.tabs.connections"))
        self.tabs.addTab(chat_tab, _("settings.tabs.chat"))
        self.tabs.addTab(users_tab, _("settings.tabs.users"))

        for widget in [
            self.telegram_bot_token_input,
            self.telegram_bot_chat_id_input,
            self.server_address_input,
            self.server_access_token_input,
            self.chat_name_input,
            self.owner_input,
            self.supergroup_template_input,
            self.cover_input,
            self.caption_input,
            self.registration_password_input,
            self.registration_email_domain_input,
        ]:
            widget.textChanged.connect(self._mark_dirty)

        self.server_port_input.valueChanged.connect(self._mark_dirty)

        for combo in [
            self.server_verify_ssl_combo,
            self.chat_type_combo,
            self.timezone_combo,
        ]:
            combo.currentIndexChanged.connect(self._mark_dirty)

        for checkbox in [
            self.voice_checkbox,
            self.stickers_checkbox,
            self.datetime_checkbox,
            self.telegram_bot_enrich_checkbox,
        ]:
            checkbox.toggled.connect(self._mark_dirty)

        self.users_table.itemChanged.connect(self._mark_dirty)
        self.users_table.itemChanged.connect(lambda *_: self._apply_user_table_visuals())

        shell_layout.addWidget(header_card)
        shell_layout.addWidget(self.tabs)


        root_layout.addWidget(settings_shell, 1)
        root_layout.addWidget(footer_card)


class MainWindow(QMainWindow):
    def _run_parse_users(self, config_path: str):

        for attr_name in ("parse_users", "main"):
            candidate = getattr(parse_users, attr_name, None)
            if callable(candidate):
                try:
                    return candidate(config_path)
                except TypeError:
                    return candidate()

        raise RuntimeError("В parse_users.py не найдена функция parse_users")

    def _run_add_users(self, config_path: str):


        for attr_name in ("register_users", "main"):
            candidate = getattr(add_users_to_server, attr_name, None)
            if callable(candidate):
                try:
                    return candidate(config_path)
                except TypeError:
                    return candidate()

        raise RuntimeError("В add_users_to_server.py не найдена функция register_users")

    def _run_build_chat(self, config_path: str):

        for attr_name in ("run_chat_transfer", "main"):
            candidate = getattr(build_chat, attr_name, None)
            if callable(candidate):
                try:
                    return candidate(config_path)
                except TypeError:
                    return candidate()

        raise RuntimeError("В build_chat.py не найдена функция run_chat_transfer")

    def _auto_parse_users(self, config_path: str):
        self._run_parse_users(config_path)

    def _run_task_with_progress(self, title: str, fn, *args, **kwargs):
        dialog = QProgressDialog(title, None, 0, 0, self)
        dialog.setWindowTitle(_("dialogs.wait"))
        dialog.setWindowIcon(QIcon(get_resource_path("assets/icon.png")))
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.setStyleSheet(
            """
            QProgressDialog {
                background-color: #FFFFFF;
                color: #163047;
            }
            QLabel {
                color: #163047;
                font-size: 13px;
            }
            QProgressBar {
                min-height: 10px;
                max-height: 10px;
                border: none;
                border-radius: 5px;
                background: #EAF8FB;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #3BB4C8;
                border-radius: 5px;
            }
            """
        )
        dialog.show()

        thread = QThread(self)
        worker = BackgroundTaskWorker(fn, *args, **kwargs)
        worker.moveToThread(thread)

        loop = QEventLoop()
        result_box = {"result": None, "error": None}

        def handle_finished(result):
            result_box["result"] = result
            dialog.close()
            loop.quit()

        def handle_failed(error_text):
            result_box["error"] = error_text
            dialog.close()
            loop.quit()

        thread.started.connect(worker.run)
        worker.finished.connect(handle_finished)
        worker.failed.connect(handle_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.start()
        dialog.show()
        QApplication.processEvents()
        loop.exec()

        if result_box["error"]:
            raise RuntimeError(result_box["error"])
        return result_box["result"]

    def _run_parse_users_with_progress(self, config_path: str):
        return self._run_task_with_progress(
            _("dialogs.parse_users"),
            self._run_parse_users,
            config_path,
        )

    def _run_add_users_with_progress(self, config_path: str):
        return self._run_task_with_progress(
            _("dialogs.register_users"),
            self._run_add_users,
            config_path,
        )

    def _run_build_chat_with_progress(self, config_path: str):
        return self._run_task_with_progress(
            _("dialogs.build_chat"),
            self._run_build_chat,
            config_path,
        )

    def _get_app_config_dir(self) -> Path:
        return get_work_dir()

    def _read_backup_metadata(self, folder_path: str) -> dict:
        result_file = Path(folder_path) / "result.json"
        with result_file.open("r", encoding="utf-8") as file:
            data = json.load(file)

        chat_id = data.get("id")
        chat_name = data.get("name", "")
        chat_type = data.get("type", "")

        if chat_id is None:
            raise ValueError("В result.json не найден id чата")

        return {
            "id": str(chat_id),
            "name": str(chat_name),
            "type": str(chat_type),
        }

    def _build_default_toml(self, folder_path: str, metadata: dict) -> str:
        telegram_export_dir = str(Path(folder_path).resolve()).replace("\\", "/")
        chat_name = metadata["name"].replace('"', '\\"')
        chat_type = metadata["type"].replace('"', '\\"')

        return f'''telegram_export_dir = "{telegram_export_dir}"

[telegram_bot]
enabled = false
token = ""
chat_id = ""

[server]
address = ""
web_port = 443
verify_ssl = false
access_token = ""

[chat]
type = "{chat_type}"
name = "{chat_name}"
supergroup_topic_name_template = "{{topic}} | {{supergroup}}"
owner = ""

[chat.datetime]
view_original_time_in_message = false
timezone = "GMT"
caption = "Отправлено: "

[chat.voice_message]
convert_voice_message_to_video = false
cover_image = "cover/ru.png"

[chat.stickers]
convert_telegram_stickers_to_webp = false

[registration]
auto = false
email_domain = ""
default_password = ""

[users]
'''

    def _get_or_create_config_path(self, folder_path: str) -> tuple[Path, bool]:
        metadata = self._read_backup_metadata(folder_path)
        config_dir = self._get_app_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        config_path = config_dir / f"chat_{metadata['id']}.toml"
        created = False
        if not config_path.exists():
            config_path.write_text(
                self._build_default_toml(folder_path, metadata),
                encoding="utf-8",
            )
            created = True
        return config_path, created

    def _config_has_users(self, config_path: Path) -> bool:
        if not config_path.exists():
            return False

        with config_path.open("rb") as file:
            data = tomllib.load(file)

        users = data.get("users")
        return isinstance(users, dict) and len(users) > 0

    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon(get_resource_path("assets/icon.png")))
        self.setWindowTitle(_("app.title"))
        self.setMinimumSize(1200, 820)

        app_font = QFont("Roboto", 10)
        self.setFont(app_font)
        self.setStyleSheet("background-color: #F6FAFC;")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.first_screen = FirstScreen(self.on_folder_selected)
        self.settings_screen = None
        self.main_layout.addWidget(self.first_screen)

    def on_folder_selected(self, folder_path):
        """Проверка папки Telegram backup, создание/загрузка конфига и переход на экран настроек"""
        result_file = Path(folder_path) / "result.json"

        if not result_file.exists():
            LOGGER.warning("Selected folder does not contain result.json: %s", folder_path)
            QMessageBox.warning(
                self,
                _("first_screen.invalid_folder"),
                _("first_screen.invalid_folder_msg"),
            )
            return

        try:
            LOGGER.info("Preparing config for selected folder: %s", folder_path)
            config_path, created = self._get_or_create_config_path(folder_path)
            LOGGER.info("Using config path: %s", config_path)
            if created or not self._config_has_users(config_path):
                LOGGER.info("Using config path: %s", config_path)
                self._run_parse_users_with_progress(str(config_path))
        except (OSError, json.JSONDecodeError, ValueError, RuntimeError, FileNotFoundError, tomllib.TOMLDecodeError) as error:
            LOGGER.exception("Failed to prepare config for folder: %s", folder_path)
            QMessageBox.warning(
                self,
                _("dialogs.config_error"),
                f"{_('dialogs.config_error_msg', error=error)}",
            )
            return

        self.first_screen.hide()

        if self.settings_screen is not None:
            self.settings_screen.deleteLater()

        self.settings_screen = SettingsScreen(
            folder_path,
            str(config_path),
            self.on_back_to_first,
            self._run_parse_users_with_progress,
            self._run_add_users_with_progress,
            self._run_build_chat_with_progress,
        )
        self.main_layout.addWidget(self.settings_screen)
        self.settings_screen.show()

    def on_back_to_first(self):
        """Возврат на первый экран"""
        if self.settings_screen is not None:
            self.settings_screen.hide()
            self.settings_screen.deleteLater()
            self.settings_screen = None
        self.first_screen.show()


def main():
    log_path = setup_file_logging()
    app = QApplication(sys.argv)

    settings = QSettings("TrueConf", "tg2tc")
    settings.sync()
    lang = settings.value("lang", None)
    if lang is None:
        system_locale = QLocale.system().name()
        lang = "ru" if system_locale.startswith("ru") else "en"
        settings.setValue("lang", lang)
    setup_i18n(lang)

    app.setWindowIcon(QIcon(get_resource_path("assets/icon.png")))
    app.setStyleSheet("""
        QMenu {
            background-color: #FFFFFF;
            color: #163047;
            border: 1px solid #D7E9EE;
            padding: 4px;
        }
        QMenu::item {
            padding: 4px 20px;
        }
        QMenu::item:selected {
            background-color: #EAF8FB;
            color: #163047;
        }
        QMenu::item:disabled {
            color: #8AA1AF;
        }
        QToolTip {
            background-color: #FFFFFF;
            color: #163047;
            border: 1px solid #D7E9EE;
            border-radius: 6px;
            padding: 6px 8px;
            font-size: 11px;
        }
    """)

    window = MainWindow()
    LOGGER.info("Main window initialized, log file: %s", log_path)
    window.show()
    if pyi_splash is not None:
        try:
            pyi_splash.close()
        except (KeyError, RuntimeError, EnvironmentError, OSError):
            pass

    ret = app.exec()
    if ret == 42:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        sys.exit(ret)


if __name__ == "__main__":
    main()
