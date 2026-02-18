from __future__ import annotations

import json
import os
import shlex
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QProcess, QThread, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import load_config
from .paths import default_data_dir
from .windows_scheduler import (
    SchedulerOperationResult,
    configure_scheduler_with_elevation,
    query_scheduler_status,
    remove_scheduler_with_elevation,
)

if TYPE_CHECKING:
    from .availability import AvailabilityConflict, AvailabilityResult

WINDOW_TITLE = "かんたん予定確認・同期"
LANG_JA = "ja"
LANG_EN = "en"
AVAILABILITY_MODEL_IDS: tuple[str, str] = (
    "LiquidAI/LFM2.5-1.2B-Thinking",
    "Qwen/Qwen3-1.7B",
)
AVAILABILITY_MAX_NEW_TOKENS = 16_384

TRANSLATIONS: dict[str, dict[str, str]] = {
    LANG_JA: {
        "window_title": "かんたん予定確認・同期",
        "title_text": "かんたん予定確認・同期",
        "hint_text": (
            "かんたん3ステップ:\n1) 接続チェック\n2) 今すぐ同期\n3) 自動同期をON（管理者権限）"
        ),
        "language_label": "表示言語:",
        "status_group_title": "状態",
        "status_config_label": "設定ファイル:",
        "status_auto_label": "自動同期:",
        "status_action_label": "操作状態:",
        "status_sync_label": "同期進捗:",
        "main_actions_title": "メイン操作",
        "activity_log_title": "実行ログ",
        "btn_setup_assistant": "0. はじめてセットアップ",
        "btn_check_connection": "1. 接続チェック",
        "btn_sync_now": "2. 今すぐ同期",
        "btn_auto_on": "3. 自動同期をON（管理者権限）",
        "btn_auto_off": "自動同期をOFF（管理者権限）",
        "btn_open_data": "データフォルダーを開く",
        "btn_settings": "設定",
        "btn_refresh_status": "自動同期の状態を更新",
        "btn_availability_popup": "4. 空き時間チェック（音声/テキスト）",
        "btn_browse_config": "設定ファイルを選択",
        "btn_browse_secret": "JSONを選択",
        "label_config_file": "config.toml:",
        "label_interval": "自動同期の間隔（秒）:",
        "settings_dialog_title": "詳細設定",
        "settings_hint": "必要なときだけ変更してください。",
        "btn_settings_save": "保存",
        "btn_settings_cancel": "キャンセル",
        "dialog_select_config": "設定ファイル config.toml を選択",
        "dialog_config_filter": "TOML files (*.toml);;All files (*)",
        "dialog_select_secret": "Google クライアントシークレット JSON を選択",
        "dialog_secret_filter": "JSON files (*.json);;All files (*)",
        "warning_config_missing_title": "設定ファイルがありません",
        "warning_config_missing_body": "設定ファイルが見つかりません:\n{path}",
        "setup_dialog_title": "はじめてセットアップ",
        "setup_hint": (
            "この画面で初期設定をまとめて完了できます。\n"
            "Google クライアントシークレット JSON は 佐々木 に依頼してください。"
        ),
        "setup_label_calendar_id": "Google カレンダーID:",
        "setup_calendar_help_html": (
            "設定ページで: 左の「マイカレンダーの設定」"
            " → 対象カレンダー → 「カレンダーの統合」→「カレンダーID」を確認。<br>"
            '<a href="https://calendar.google.com/calendar/u/0/r/settings" '
            'style="color:#0b5ed7; font-weight:700; text-decoration:underline;">'
            "Google カレンダー設定ページを開く</a>"
        ),
        "setup_label_client_secret": "クライアントシークレット JSON:",
        "setup_label_interval": "自動同期の間隔（秒）:",
        "setup_label_tls": "社内プロキシの証明書エラーを無視する（推奨）",
        "setup_save_button": "設定を保存して接続チェック",
        "setup_cancel_button": "キャンセル",
        "setup_prompt_title": "初期設定が必要です",
        "setup_prompt_body": "設定ファイルが見つかりません。セットアップを開始しますか？",
        "warning_setup_title": "セットアップエラー",
        "warning_setup_calendar_required": "Google カレンダーIDを入力してください。",
        "warning_setup_secret_required": (
            "クライアントシークレット JSON を選択してください。\n"
            "ファイルは 佐々木 に依頼してください。"
        ),
        "warning_setup_secret_missing": "クライアントシークレット JSON が見つかりません:\n{path}",
        "warning_setup_secret_not_json": "クライアントシークレットは JSON オブジェクトである必要があります。",
        "warning_setup_secret_installed": "Desktop app 用 JSON ではありません。'installed' オブジェクトが必要です。",
        "warning_setup_secret_missing_fields": "クライアントシークレット JSON の必須項目が不足しています: {fields}",
        "warning_setup_secret_redirect": "Desktop app 用 JSON ではありません。redirect_uris に localhost/127.0.0.1 が必要です。",
        "warning_setup_secret_invalid_json": "クライアントシークレット JSON の読み込みに失敗しました: {error}",
        "log_setup_started": "セットアップを開始しました。",
        "log_setup_saved_secret": "クライアントシークレットを保存しました: {path}",
        "log_setup_saved_config": "設定ファイルを保存しました: {path}",
        "log_setup_done": "セットアップ完了。接続チェックを実行します。",
        "log_config_not_found": "設定ファイルが見つかりません: {path}",
        "log_failed_load_config": "設定ファイルの読み込みに失敗しました: {error}",
        "log_another_running": "ほかの処理を実行中です。完了までお待ちください。",
        "log_request_accepted": "受付: {action}（処理中）",
        "log_starting": "開始: {action}",
        "log_command": "実行コマンド: {command}",
        "log_start_failed": "{action} の起動に失敗しました。",
        "log_status_refresh_fail": "自動同期の状態更新に失敗しました: {error}",
        "log_done_success": "正常に完了しました。",
        "log_done_error": "エラーで終了しました。終了コード: {exit_code}",
        "log_process_failure": "プロセスエラー: {error}",
        "action_manual_sync": "手動同期",
        "action_doctor_check": "接続チェック",
        "action_auto_on": "自動同期ON設定",
        "action_auto_off": "自動同期OFF設定",
        "action_refresh_status": "自動同期状態の更新",
        "action_availability_check": "空き時間チェック",
        "action_voice_input": "音声入力",
        "log_auto_on_success": "自動同期をONにしました。{message}",
        "log_auto_on_fail": "自動同期をONにできませんでした。{message}",
        "log_auto_off_success": "自動同期をOFFにしました。{message}",
        "log_auto_off_fail": "自動同期をOFFにできませんでした。{message}",
        "log_status_on": "自動同期の状態: ON",
        "log_status_off": "自動同期の状態: OFF",
        "log_status_error": "自動同期の状態確認エラー: {status}",
        "status_action_idle": "操作できます",
        "status_action_busy": "処理中: {action}",
        "sync_progress_idle": "未実行",
        "sync_progress_running": "同期中...",
        "sync_progress_done": "完了",
        "sync_progress_failed": "失敗",
        "sync_progress_summary": "Outlook {outlook} / Google {google}",
        "sync_progress_step": "{stage} ({done}/{total})",
        "sync_stage_scan_outlook": "Outlookを確認中",
        "sync_stage_scan_google": "Googleを確認中",
        "sync_stage_reconcile": "差分を確認中",
        "sync_stage_create_google": "Googleへ反映中",
        "sync_stage_create_outlook": "Outlookへ反映中",
        "sync_stage_finalize": "最終処理中",
        "status_config_ready": "準備OK",
        "status_config_missing": "見つかりません",
        "status_config_invalid": "設定エラー",
        "status_config_unknown": "不明",
        "status_auto_on": "ON",
        "status_auto_off": "OFF",
        "status_auto_loading": "更新中...",
        "status_auto_unknown": "不明",
        "availability_dialog_title": "空き時間チェック（音声/テキスト）",
        "availability_hint": (
            "例: 明日の10時から17時\n"
            "音声入力は「録音して入力」で最大7秒まで録音できます（途中で停止可）。"
        ),
        "availability_input_label": "確認したい時間:",
        "availability_input_placeholder": "例：明日の10時から13時に東京駅で",
        "availability_model_label": "解析モデル:",
        "availability_model_lfm": "LiquidAI/LFM2.5-1.2B-Thinking",
        "availability_model_qwen": "Qwen/Qwen3-1.7B",
        "availability_model_hint": "thinking モード固定 / 最大出力 16384 トークン",
        "availability_llm_log_label": "LLMログ（<think> / <answer>）:",
        "availability_llm_log_waiting": "ここに <think> と <answer> が逐次表示されます。",
        "availability_check_button": "空き時間を確認",
        "availability_voice_button": "録音して入力（最大7秒）",
        "availability_voice_button_stop": "録音停止",
        "availability_close_button": "閉じる",
        "availability_status_ready": "入力待ち",
        "availability_status_listening": "録音中...（最大7秒）",
        "availability_status_stopping": "録音停止しました。書き起こし中...",
        "availability_status_checking": "予定を確認中...",
        "availability_status_available": "この時間は空いています",
        "availability_status_busy": "この時間は予定があります",
        "availability_status_error": "エラー",
        "availability_result_waiting": "ここに結果が表示されます。",
        "availability_result_window": "確認時間: {start} - {end}",
        "availability_result_free": "判定: 空き",
        "availability_result_busy": "判定: 予定あり（{count}件）",
        "availability_result_conflict": "{source}: {start} - {end} / {summary}",
        "availability_result_all_day": "終日",
        "availability_source_outlook": "Outlook",
        "availability_source_google": "Google",
        "availability_summary_empty": "(無題)",
        "warning_availability_title": "空き時間チェック",
        "warning_availability_query_required": "確認したい時間を入力してください。",
        "warning_availability_voice_error": "音声入力に失敗しました: {error}",
        "warning_availability_check_error": "空き時間の確認に失敗しました: {error}",
    },
    LANG_EN: {
        "window_title": "BridgeCal Calendar Sync",
        "title_text": "BridgeCal Calendar Sync",
        "hint_text": (
            "Simple 3 steps:\n1) Check Connection\n2) Sync Now\n3) Turn ON Auto Sync (Admin)"
        ),
        "language_label": "Language:",
        "status_group_title": "Status",
        "status_config_label": "Config file:",
        "status_auto_label": "Auto Sync:",
        "status_action_label": "Operation:",
        "status_sync_label": "Sync Progress:",
        "main_actions_title": "Main Actions",
        "activity_log_title": "Activity Log",
        "btn_setup_assistant": "0. First-time Setup",
        "btn_check_connection": "1. Check Connection",
        "btn_sync_now": "2. Sync Now",
        "btn_auto_on": "3. Turn ON Auto Sync (Admin)",
        "btn_auto_off": "Turn OFF Auto Sync (Admin)",
        "btn_open_data": "Open Data Folder",
        "btn_settings": "Settings",
        "btn_refresh_status": "Refresh Auto Sync Status",
        "btn_availability_popup": "4. Check Availability (Voice/Text)",
        "btn_browse_config": "Browse Config",
        "btn_browse_secret": "Browse JSON",
        "label_config_file": "config.toml:",
        "label_interval": "Auto Sync interval (seconds):",
        "settings_dialog_title": "Settings",
        "settings_hint": "Change these only when needed.",
        "btn_settings_save": "Save",
        "btn_settings_cancel": "Cancel",
        "dialog_select_config": "Select BridgeCal config.toml",
        "dialog_config_filter": "TOML files (*.toml);;All files (*)",
        "dialog_select_secret": "Select Google client secret JSON",
        "dialog_secret_filter": "JSON files (*.json);;All files (*)",
        "warning_config_missing_title": "Config Missing",
        "warning_config_missing_body": "Config file was not found:\n{path}",
        "setup_dialog_title": "First-time Setup",
        "setup_hint": (
            "Complete initial setup in this one screen.\n"
            "Ask Sasaki for the Google client secret JSON file."
        ),
        "setup_label_calendar_id": "Google calendar ID:",
        "setup_calendar_help_html": (
            "On the Settings page: Settings for my calendars -> your calendar -> "
            "Integrate calendar -> Calendar ID.<br>"
            '<a href="https://calendar.google.com/calendar/u/0/r/settings" '
            'style="color:#0b5ed7; font-weight:700; text-decoration:underline;">'
            "Open Google Calendar settings</a>"
        ),
        "setup_label_client_secret": "Client secret JSON:",
        "setup_label_interval": "Auto Sync interval (seconds):",
        "setup_label_tls": "Ignore TLS certificate errors for corporate proxy (recommended)",
        "setup_save_button": "Save setup and run doctor",
        "setup_cancel_button": "Cancel",
        "setup_prompt_title": "Setup Required",
        "setup_prompt_body": "Config file is missing. Start setup now?",
        "warning_setup_title": "Setup Error",
        "warning_setup_calendar_required": "Enter Google calendar ID.",
        "warning_setup_secret_required": ("Select client secret JSON.\nAsk Sasaki for this file."),
        "warning_setup_secret_missing": "Client secret JSON was not found:\n{path}",
        "warning_setup_secret_not_json": "Client secret must be a JSON object.",
        "warning_setup_secret_installed": "This is not Desktop app OAuth JSON. Missing 'installed' object.",
        "warning_setup_secret_missing_fields": "Client secret JSON is missing required fields: {fields}",
        "warning_setup_secret_redirect": "This is not Desktop app OAuth JSON. redirect_uris must include localhost/127.0.0.1.",
        "warning_setup_secret_invalid_json": "Failed to read client secret JSON: {error}",
        "log_setup_started": "Starting setup assistant.",
        "log_setup_saved_secret": "Saved client secret: {path}",
        "log_setup_saved_config": "Saved config file: {path}",
        "log_setup_done": "Setup complete. Running doctor check.",
        "log_config_not_found": "Config not found: {path}",
        "log_failed_load_config": "Failed to load config: {error}",
        "log_another_running": "Another BridgeCal command is running. Wait for it to finish first.",
        "log_request_accepted": "Accepted: {action} (processing)",
        "log_starting": "Starting: {action}",
        "log_command": "Command: {command}",
        "log_start_failed": "Failed to start process for {action}.",
        "log_status_refresh_fail": "Failed to refresh Auto Sync status: {error}",
        "log_done_success": "Completed successfully.",
        "log_done_error": "Completed with errors. Exit code: {exit_code}",
        "log_process_failure": "Process failure: {error}",
        "action_manual_sync": "Manual sync",
        "action_doctor_check": "Doctor check",
        "action_auto_on": "Enable Auto Sync",
        "action_auto_off": "Disable Auto Sync",
        "action_refresh_status": "Refresh Auto Sync status",
        "action_availability_check": "Availability check",
        "action_voice_input": "Voice input",
        "log_auto_on_success": "Auto Sync is ON. {message}",
        "log_auto_on_fail": "Could not enable Auto Sync. {message}",
        "log_auto_off_success": "Auto Sync is OFF. {message}",
        "log_auto_off_fail": "Could not disable Auto Sync. {message}",
        "log_status_on": "Auto Sync status: ON",
        "log_status_off": "Auto Sync status: OFF",
        "log_status_error": "Auto Sync status error: {status}",
        "status_action_idle": "Idle",
        "status_action_busy": "Working: {action}",
        "sync_progress_idle": "Not started",
        "sync_progress_running": "Syncing...",
        "sync_progress_done": "Done",
        "sync_progress_failed": "Failed",
        "sync_progress_summary": "Outlook {outlook} / Google {google}",
        "sync_progress_step": "{stage} ({done}/{total})",
        "sync_stage_scan_outlook": "Scanning Outlook",
        "sync_stage_scan_google": "Scanning Google",
        "sync_stage_reconcile": "Reconciling",
        "sync_stage_create_google": "Applying to Google",
        "sync_stage_create_outlook": "Applying to Outlook",
        "sync_stage_finalize": "Finalizing",
        "status_config_ready": "Ready",
        "status_config_missing": "Missing",
        "status_config_invalid": "Invalid",
        "status_config_unknown": "Unknown",
        "status_auto_on": "ON",
        "status_auto_off": "OFF",
        "status_auto_loading": "Loading...",
        "status_auto_unknown": "Unknown",
        "availability_dialog_title": "Availability Check (Voice/Text)",
        "availability_hint": (
            "Example: tomorrow 10:00-17:00\n"
            "Use 'Record Voice Input' to capture up to 7 seconds (you can stop early)."
        ),
        "availability_input_label": "Time to check:",
        "availability_input_placeholder": "Example: tomorrow 10:00-13:00 at Tokyo Station",
        "availability_model_label": "Parser model:",
        "availability_model_lfm": "LiquidAI/LFM2.5-1.2B-Thinking",
        "availability_model_qwen": "Qwen/Qwen3-1.7B",
        "availability_model_hint": "Thinking mode forced / max output 16384 tokens",
        "availability_llm_log_label": "LLM log (<think> / <answer>):",
        "availability_llm_log_waiting": "<think> and <answer> will stream here.",
        "availability_check_button": "Check Availability",
        "availability_voice_button": "Record Voice Input (max 7s)",
        "availability_voice_button_stop": "Stop Recording",
        "availability_close_button": "Close",
        "availability_status_ready": "Ready",
        "availability_status_listening": "Recording... (up to 7s)",
        "availability_status_stopping": "Stopping recording...",
        "availability_status_checking": "Checking calendars...",
        "availability_status_available": "This time is available",
        "availability_status_busy": "This time is busy",
        "availability_status_error": "Error",
        "availability_result_waiting": "Results will appear here.",
        "availability_result_window": "Window: {start} - {end}",
        "availability_result_free": "Result: Available",
        "availability_result_busy": "Result: Busy ({count})",
        "availability_result_conflict": "{source}: {start} - {end} / {summary}",
        "availability_result_all_day": "All-day",
        "availability_source_outlook": "Outlook",
        "availability_source_google": "Google",
        "availability_summary_empty": "(No title)",
        "warning_availability_title": "Availability Check",
        "warning_availability_query_required": "Enter the time you want to check.",
        "warning_availability_voice_error": "Voice input failed: {error}",
        "warning_availability_check_error": "Availability check failed: {error}",
    },
}

APP_STYLESHEET = """
QWidget {
    background-color: #f5f7fb;
    color: #0f172a;
    font-size: 16px;
}
QGroupBox {
    border: 2px solid #cbd5e1;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 10px;
    font-size: 18px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLabel#titleText {
    font-size: 30px;
    font-weight: 800;
}
QLabel#hintText {
    font-size: 18px;
    color: #334155;
}
QPushButton {
    min-height: 52px;
    font-size: 20px;
    font-weight: 700;
    border: 2px solid #334155;
    border-radius: 12px;
    background-color: #ffffff;
    padding: 6px 12px;
}
QPushButton#primaryAction {
    background-color: #0b5ed7;
    border-color: #084298;
    color: #ffffff;
}
QPushButton#dangerAction {
    background-color: #b02a37;
    border-color: #842029;
    color: #ffffff;
}
QPushButton#secondaryAction {
    min-height: 44px;
    font-size: 16px;
    font-weight: 600;
}
QPushButton:disabled {
    background-color: #cbd5e1;
    border-color: #94a3b8;
    color: #64748b;
}
QComboBox,
QLineEdit,
QSpinBox,
QPlainTextEdit {
    background-color: #ffffff;
    border: 2px solid #94a3b8;
    border-radius: 8px;
    padding: 6px;
    font-size: 16px;
}
QPlainTextEdit {
    min-height: 150px;
}
QProgressBar {
    border: 2px solid #94a3b8;
    border-radius: 8px;
    background: #ffffff;
    text-align: center;
    font-size: 14px;
    min-height: 24px;
}
QProgressBar::chunk {
    background-color: #0b5ed7;
    border-radius: 6px;
}
"""


class _BackgroundWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self._operation = operation

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._operation()
        except Exception as exc:  # pragma: no cover - defensive guard
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class BridgeCalWindow(QWidget):
    def __init__(self, config_path: Path | None = None) -> None:
        super().__init__()
        self._process: QProcess | None = None
        self._active_action_key: str | None = None
        self._background_thread: QThread | None = None
        self._background_worker: _BackgroundWorker | None = None
        self._background_on_success: Callable[[object], None] | None = None
        self._background_on_failure: Callable[[str], None] | None = None
        self._status_timer = QTimer(self)
        self._last_scheduler_status: str | None = None
        self._scheduler_status_loading = False
        self._sync_progress_visible = False
        self._sync_progress_state = "idle"
        self._sync_progress_done_count: int | None = None
        self._sync_progress_total_count: int | None = None
        self._sync_progress_stage: str | None = None
        self._sync_progress_outlook: int | None = None
        self._sync_progress_google: int | None = None
        self._setup_prompt_shown = False
        self._config_status_key = "status_config_unknown"
        self._config_status_tone = "neutral"
        self._availability_popup_open = False
        self._availability_model_id = self._initial_availability_model_id()

        self.setWindowTitle(WINDOW_TITLE)
        self.resize(920, 660)
        self.setStyleSheet(APP_STYLESHEET)

        default_config_path = default_data_dir() / "config.toml"
        initial_config_path = config_path or default_config_path

        self.language_label = QLabel()
        self.language_selector = QComboBox()
        self.language_selector.addItem("日本語", LANG_JA)
        self.language_selector.addItem("English", LANG_EN)
        self.language_selector.setCurrentIndex(0)

        self.title_label = QLabel("かんたん予定確認・同期")
        self.title_label.setObjectName("titleText")
        self.hint_label = QLabel(
            "Simple steps:\n1) Check Connection\n2) Sync Now\n3) Turn ON Auto Sync (Admin)"
        )
        self.hint_label.setObjectName("hintText")
        self.hint_label.setWordWrap(True)

        self.config_status = QLabel("Unknown")
        self.scheduler_status = QLabel("Unknown")
        self.action_status = QLabel("Idle")
        self.sync_progress_status = QLabel("Not started")
        self.status_config_label = QLabel("Config:")
        self.status_auto_label = QLabel("Auto Sync:")
        self.status_action_label = QLabel("Operation:")
        self.status_sync_label = QLabel("Sync Progress:")

        self.config_path_input = QLineEdit(str(initial_config_path))
        self.interval_input = QSpinBox()
        self.interval_input.setRange(30, 86_400)
        self.interval_input.setValue(120)
        self.sync_progress_bar = QProgressBar()
        self.sync_progress_bar.setRange(0, 100)
        self.sync_progress_bar.setValue(0)
        self.sync_progress_bar.setFormat("0%")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)

        self.setup_assistant_button = QPushButton("0. First-time Setup")
        self.doctor_button = QPushButton("1. Check Connection")
        self.manual_sync_button = QPushButton("2. Sync Now")
        self.setup_scheduler_button = QPushButton("3. Turn ON Auto Sync (Admin)")
        self.availability_popup_button = QPushButton("4. Check Availability (Voice/Text)")
        self.remove_scheduler_button = QPushButton("Turn OFF Auto Sync (Admin)")
        self.open_data_dir_button = QPushButton("Open Data Folder")
        self.settings_button = QPushButton("Settings")

        self.refresh_status_button = QPushButton("Refresh Scheduler Status")

        self.setup_assistant_button.setObjectName("primaryAction")
        self.doctor_button.setObjectName("primaryAction")
        self.manual_sync_button.setObjectName("primaryAction")
        self.setup_scheduler_button.setObjectName("primaryAction")
        self.availability_popup_button.setObjectName("primaryAction")
        self.remove_scheduler_button.setObjectName("dangerAction")
        self.open_data_dir_button.setObjectName("secondaryAction")
        self.settings_button.setObjectName("secondaryAction")
        self.refresh_status_button.setObjectName("secondaryAction")

        self._build_layout()
        self._wire_events()
        self._apply_language()
        self._refresh_config_values(log_errors=False)
        QTimer.singleShot(350, self._offer_setup_assistant_if_needed)

        self._status_timer.timeout.connect(
            lambda: self._refresh_scheduler_status(
                emit_log=False,
                interactive=False,
                show_loading=False,
            )
        )
        self._status_timer.start(10_000)
        # Defer first scheduler query so window paints quickly on startup.
        QTimer.singleShot(
            150,
            lambda: self._refresh_scheduler_status(
                emit_log=False,
                interactive=False,
                show_loading=False,
            ),
        )

    def _language(self) -> str:
        value = self.language_selector.currentData()
        if isinstance(value, str) and value in TRANSLATIONS:
            return value
        return LANG_JA

    def _t(self, key: str, **kwargs: object) -> str:
        catalog = TRANSLATIONS.get(self._language(), TRANSLATIONS[LANG_JA])
        text = catalog.get(key, key)
        return text.format(**kwargs)

    def _initial_availability_model_id(self) -> str:
        env_value = os.environ.get("BRIDGECAL_LFM25_LOCAL_MODEL", "").strip()
        if env_value in AVAILABILITY_MODEL_IDS:
            return env_value
        return AVAILABILITY_MODEL_IDS[0]

    def _apply_language(self) -> None:
        self.setWindowTitle(self._t("window_title"))
        self.title_label.setText(self._t("title_text"))
        self.hint_label.setText(self._t("hint_text"))
        self.language_label.setText(self._t("language_label"))
        self.status_group.setTitle(self._t("status_group_title"))
        self.main_actions_group.setTitle(self._t("main_actions_title"))
        self.log_group.setTitle(self._t("activity_log_title"))
        self.status_config_label.setText(self._t("status_config_label"))
        self.status_auto_label.setText(self._t("status_auto_label"))
        self.status_action_label.setText(self._t("status_action_label"))
        self.status_sync_label.setText(self._t("status_sync_label"))

        self.setup_assistant_button.setText(self._t("btn_setup_assistant"))
        self.doctor_button.setText(self._t("btn_check_connection"))
        self.manual_sync_button.setText(self._t("btn_sync_now"))
        self.setup_scheduler_button.setText(self._t("btn_auto_on"))
        self.availability_popup_button.setText(self._t("btn_availability_popup"))
        self.remove_scheduler_button.setText(self._t("btn_auto_off"))
        self.open_data_dir_button.setText(self._t("btn_open_data"))
        self.settings_button.setText(self._t("btn_settings"))
        self.refresh_status_button.setText(self._t("btn_refresh_status"))
        self._update_action_status_badge()
        self._refresh_sync_progress_label()

    def _build_layout(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        header_row.addWidget(self.title_label, stretch=1)
        header_row.addWidget(self.language_label)
        header_row.addWidget(self.language_selector)
        root_layout.addLayout(header_row)

        root_layout.addWidget(self.hint_label)

        self.status_group = QGroupBox("Status")
        self.status_form_layout = QFormLayout(self.status_group)
        self.status_form_layout.addRow(self.status_config_label, self.config_status)
        self.status_form_layout.addRow(self.status_auto_label, self.scheduler_status)
        self.status_form_layout.addRow(self.status_action_label, self.action_status)
        sync_row = QHBoxLayout()
        sync_row.setSpacing(8)
        sync_row.addWidget(self.sync_progress_bar, stretch=1)
        sync_row.addWidget(self.sync_progress_status)
        self.sync_progress_widget = QWidget(self.status_group)
        self.sync_progress_widget.setLayout(sync_row)
        self.status_form_layout.addRow(self.status_sync_label, self.sync_progress_widget)
        self._set_sync_progress_visible(False)
        root_layout.addWidget(self.status_group)

        self.main_actions_group = QGroupBox("Main Actions")
        actions_layout = QGridLayout(self.main_actions_group)
        actions_layout.setHorizontalSpacing(10)
        actions_layout.setVerticalSpacing(10)
        actions_layout.addWidget(self.setup_assistant_button, 0, 0, 1, 2)
        actions_layout.addWidget(self.doctor_button, 1, 0)
        actions_layout.addWidget(self.manual_sync_button, 1, 1)
        actions_layout.addWidget(self.setup_scheduler_button, 2, 0)
        actions_layout.addWidget(self.remove_scheduler_button, 2, 1)
        actions_layout.addWidget(self.availability_popup_button, 3, 0, 1, 2)
        root_layout.addWidget(self.main_actions_group)

        tools_row = QHBoxLayout()
        tools_row.addWidget(self.open_data_dir_button)
        tools_row.addWidget(self.settings_button)
        tools_row.addWidget(self.refresh_status_button)
        root_layout.addLayout(tools_row)

        self.log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(self.log_group)
        log_layout.addWidget(self.output)
        root_layout.addWidget(self.log_group, stretch=1)

    def _wire_events(self) -> None:
        self.setup_assistant_button.clicked.connect(self._open_setup_assistant)
        self.manual_sync_button.clicked.connect(self._run_manual_sync)
        self.doctor_button.clicked.connect(self._run_doctor)
        self.setup_scheduler_button.clicked.connect(self._setup_scheduler)
        self.remove_scheduler_button.clicked.connect(self._remove_scheduler)
        self.availability_popup_button.clicked.connect(self._open_availability_popup)
        self.refresh_status_button.clicked.connect(self._refresh_scheduler_status_from_button)
        self.open_data_dir_button.clicked.connect(self._open_data_dir)
        self.settings_button.clicked.connect(self._open_settings)
        self.language_selector.currentIndexChanged.connect(self._on_language_changed)

    def _append_output(self, message: str) -> None:
        text = message.rstrip()
        if not text:
            return
        self.output.appendPlainText(text)

    def _action_label(self, action_key: str) -> str:
        return self._t(action_key)

    def _update_action_status_badge(self) -> None:
        if self._active_action_key is None:
            self._set_badge(self.action_status, self._t("status_action_idle"), tone="neutral")
            return
        self._set_badge(
            self.action_status,
            self._t("status_action_busy", action=self._action_label(self._active_action_key)),
            tone="busy",
        )

    def _set_sync_progress_visible(self, visible: bool) -> None:
        self._sync_progress_visible = visible
        self.status_sync_label.setVisible(visible)
        self.sync_progress_widget.setVisible(visible)

    def _refresh_sync_progress_label(self) -> None:
        if self._sync_progress_state == "idle":
            self.sync_progress_status.setText(self._t("sync_progress_idle"))
            return
        if self._sync_progress_state == "running":
            if (
                self._sync_progress_done_count is not None
                and self._sync_progress_total_count is not None
                and self._sync_progress_stage is not None
            ):
                self.sync_progress_status.setText(
                    self._t(
                        "sync_progress_step",
                        stage=self._sync_stage_label(self._sync_progress_stage),
                        done=self._sync_progress_done_count,
                        total=self._sync_progress_total_count,
                    )
                )
                return
            self.sync_progress_status.setText(self._t("sync_progress_running"))
            return
        if self._sync_progress_state == "done":
            if self._sync_progress_outlook is not None and self._sync_progress_google is not None:
                self.sync_progress_status.setText(
                    self._t(
                        "sync_progress_summary",
                        outlook=self._sync_progress_outlook,
                        google=self._sync_progress_google,
                    )
                )
                return
            self.sync_progress_status.setText(self._t("sync_progress_done"))
            return
        if self._sync_progress_state == "failed":
            self.sync_progress_status.setText(self._t("sync_progress_failed"))

    def _set_sync_progress_running(self) -> None:
        self._set_sync_progress_visible(True)
        self._sync_progress_state = "running"
        self._sync_progress_done_count = None
        self._sync_progress_total_count = None
        self._sync_progress_stage = None
        self._sync_progress_outlook = None
        self._sync_progress_google = None
        self.sync_progress_bar.setRange(0, 0)
        self.sync_progress_bar.setFormat("")
        self._refresh_sync_progress_label()

    def _sync_stage_label(self, stage: str) -> str:
        key = f"sync_stage_{stage}"
        translated = self._t(key)
        if translated == key:
            return stage
        return translated

    def _set_sync_progress_step(self, *, done: int, total: int, stage: str) -> None:
        safe_total = max(total, 1)
        safe_done = max(0, min(done, safe_total))
        percent = int((safe_done * 100) / safe_total)

        self._set_sync_progress_visible(True)
        self._sync_progress_state = "running"
        self._sync_progress_done_count = safe_done
        self._sync_progress_total_count = safe_total
        self._sync_progress_stage = stage

        self.sync_progress_bar.setRange(0, safe_total)
        self.sync_progress_bar.setValue(safe_done)
        self.sync_progress_bar.setFormat(f"{percent}%")
        self._refresh_sync_progress_label()

    def _set_sync_progress_done(
        self, *, outlook: int | None = None, google: int | None = None
    ) -> None:
        self._sync_progress_state = "done"
        self._sync_progress_done_count = None
        self._sync_progress_total_count = None
        self._sync_progress_stage = None
        self._sync_progress_outlook = outlook
        self._sync_progress_google = google
        self.sync_progress_bar.setRange(0, 100)
        self.sync_progress_bar.setValue(100)
        self.sync_progress_bar.setFormat("100%")
        self._refresh_sync_progress_label()

    def _set_sync_progress_failed(self) -> None:
        self._sync_progress_state = "failed"
        self._sync_progress_done_count = None
        self._sync_progress_total_count = None
        self._sync_progress_stage = None
        self._sync_progress_outlook = None
        self._sync_progress_google = None
        self.sync_progress_bar.setRange(0, 100)
        self.sync_progress_bar.setValue(0)
        self.sync_progress_bar.setFormat("0%")
        self._refresh_sync_progress_label()

    def _try_apply_sync_step_progress(self, line: str) -> bool:
        text = line.strip()
        if not text.startswith("sync_progress:"):
            return False

        payload = text[len("sync_progress:") :].strip()
        parts = payload.split()
        values: dict[str, str] = {}
        for token in parts:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            values[key] = value

        try:
            done = int(values["done"])
            total = int(values["total"])
        except (KeyError, ValueError):
            return False

        stage = values.get("stage", "reconcile")
        self._set_sync_progress_step(done=done, total=total, stage=stage)
        return True

    def _try_apply_sync_summary_progress(self, line: str) -> bool:
        text = line.strip()
        if not text.startswith("sync:"):
            return False

        parts = text.split()
        values: dict[str, int] = {}
        for token in parts:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            try:
                values[key] = int(value)
            except ValueError:
                continue

        if "outlook" not in values or "google" not in values:
            return False

        self._set_sync_progress_done(outlook=values["outlook"], google=values["google"])
        return True

    def _begin_action(self, action_key: str) -> bool:
        if self._active_action_key is not None:
            self._append_output(self._t("log_another_running"))
            return False
        self._active_action_key = action_key
        self._set_command_buttons_enabled(False)
        self.language_selector.setEnabled(False)
        self._update_action_status_badge()
        self._append_output(self._t("log_request_accepted", action=self._action_label(action_key)))
        return True

    def _finish_action(self) -> None:
        self._active_action_key = None
        self._set_command_buttons_enabled(True)
        self.language_selector.setEnabled(True)
        self._update_action_status_badge()

    def _start_background_operation(
        self,
        *,
        operation: Callable[[], object],
        on_success: Callable[[object], None],
        on_failure: Callable[[str], None],
    ) -> bool:
        if self._background_thread is not None:
            return False

        thread = QThread(self)
        worker = _BackgroundWorker(operation)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_background_success)
        worker.failed.connect(self._on_background_failure)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._background_thread = thread
        self._background_worker = worker
        self._background_on_success = on_success
        self._background_on_failure = on_failure
        thread.start()
        return True

    def _clear_background_refs(self) -> None:
        self._background_thread = None
        self._background_worker = None
        self._background_on_success = None
        self._background_on_failure = None

    def _on_background_success(self, result: object) -> None:
        callback = self._background_on_success
        self._clear_background_refs()
        if callback is not None:
            callback(result)

    def _on_background_failure(self, error: str) -> None:
        callback = self._background_on_failure
        self._clear_background_refs()
        if callback is not None:
            callback(error)

    def _current_config_path(self) -> Path:
        return Path(self.config_path_input.text().strip()).expanduser()

    def _refresh_config_values(self, *, log_errors: bool) -> None:
        config_path = self._current_config_path()
        if not config_path.exists():
            self._set_config_status("status_config_missing", tone="bad")
            if log_errors:
                self._append_output(self._t("log_config_not_found", path=config_path))
            return

        try:
            cfg = load_config(config_path)
        except Exception as exc:
            self._set_config_status("status_config_invalid", tone="bad")
            if log_errors:
                self._append_output(self._t("log_failed_load_config", error=exc))
            return

        self.interval_input.setValue(cfg.sync.interval_seconds)
        self._set_config_status("status_config_ready", tone="good")

    def _set_config_status(self, status_key: str, *, tone: str) -> None:
        self._config_status_key = status_key
        self._config_status_tone = tone
        self._set_badge(self.config_status, self._t(status_key), tone=tone)

    def _set_badge(self, label: QLabel, text: str, *, tone: str) -> None:
        if tone == "good":
            style = (
                "QLabel { background: #d1fae5; color: #065f46; border: 2px solid #10b981; "
                "border-radius: 8px; padding: 6px 10px; font-size: 18px; font-weight: 700; }"
            )
        elif tone == "busy":
            style = (
                "QLabel { background: #dbeafe; color: #1e3a8a; border: 2px solid #2563eb; "
                "border-radius: 8px; padding: 6px 10px; font-size: 18px; font-weight: 700; }"
            )
        elif tone == "bad":
            style = (
                "QLabel { background: #fee2e2; color: #7f1d1d; border: 2px solid #ef4444; "
                "border-radius: 8px; padding: 6px 10px; font-size: 18px; font-weight: 700; }"
            )
        else:
            style = (
                "QLabel { background: #e2e8f0; color: #1e293b; border: 2px solid #94a3b8; "
                "border-radius: 8px; padding: 6px 10px; font-size: 18px; font-weight: 700; }"
            )
        label.setText(text)
        label.setStyleSheet(style)

    def _set_scheduler_loading(self, loading: bool) -> None:
        self._scheduler_status_loading = loading
        if loading:
            self._set_badge(self.scheduler_status, self._t("status_auto_loading"), tone="busy")
            self.refresh_status_button.setEnabled(False)
            return
        if self._active_action_key is None:
            self.refresh_status_button.setEnabled(True)

    def _offer_setup_assistant_if_needed(self) -> None:
        if self._setup_prompt_shown:
            return
        if self._config_status_key == "status_config_ready":
            return
        self._setup_prompt_shown = True

        response = QMessageBox.question(
            self,
            self._t("setup_prompt_title"),
            self._t("setup_prompt_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if response == QMessageBox.StandardButton.Yes:
            self._open_setup_assistant()

    def _show_setup_error(self, message: str) -> None:
        QMessageBox.warning(self, self._t("warning_setup_title"), message)

    def _parse_client_secret_json(self, path: Path) -> dict[str, Any]:
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
            payload: Any = json.loads(text)
        except Exception as exc:
            raise ValueError(self._t("warning_setup_secret_invalid_json", error=exc)) from exc

        if not isinstance(payload, dict):
            raise ValueError(self._t("warning_setup_secret_not_json"))
        return payload

    def _validate_desktop_client_secret_json(self, payload: dict[str, Any]) -> None:
        installed = payload.get("installed")
        if not isinstance(installed, dict):
            raise ValueError(self._t("warning_setup_secret_installed"))

        required_fields = ("client_id", "client_secret", "auth_uri", "token_uri", "redirect_uris")
        missing = [name for name in required_fields if not installed.get(name)]
        if missing:
            raise ValueError(
                self._t(
                    "warning_setup_secret_missing_fields",
                    fields=", ".join(missing),
                )
            )

        redirect_uris = installed.get("redirect_uris")
        if not isinstance(redirect_uris, list):
            raise ValueError(self._t("warning_setup_secret_redirect"))

        has_local_redirect = any(
            isinstance(uri, str)
            and (uri.startswith("http://localhost") or uri.startswith("http://127.0.0.1"))
            for uri in redirect_uris
        )
        if not has_local_redirect:
            raise ValueError(self._t("warning_setup_secret_redirect"))

    def _toml_escape(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _build_setup_config_toml(
        self,
        *,
        data_dir: Path,
        calendar_id: str,
        interval_seconds: int,
        insecure_tls_skip_verify: bool,
    ) -> str:
        data_dir_literal = self._toml_escape(data_dir.as_posix())
        calendar_id_literal = self._toml_escape(calendar_id)
        tls_literal = "true" if insecure_tls_skip_verify else "false"
        return (
            f'data_dir = "{data_dir_literal}"\n\n'
            "[outlook]\n"
            "past_days = 30\n"
            "future_days = 180\n\n"
            "[google]\n"
            f'calendar_id = "{calendar_id_literal}"\n'
            'client_secret_path = "google_client_secret.json"\n'
            'token_path = "google_token.json"\n'
            f"insecure_tls_skip_verify = {tls_literal}\n\n"
            "[sync]\n"
            f"interval_seconds = {interval_seconds}\n"
            'redaction_mode = "none"\n'
        )

    def _open_setup_assistant(self) -> None:
        if self._active_action_key is not None or self._background_thread is not None:
            self._append_output(self._t("log_another_running"))
            return

        config_path = self._current_config_path()
        if not config_path.is_absolute():
            config_path = (Path.cwd() / config_path).resolve()

        default_calendar_id = "primary"
        default_interval = int(self.interval_input.value())
        default_insecure_tls_skip_verify = True
        default_secret_path = config_path.parent / "google_client_secret.json"

        if config_path.exists():
            try:
                cfg = load_config(config_path)
                default_calendar_id = cfg.google.calendar_id
                default_interval = cfg.sync.interval_seconds
                default_insecure_tls_skip_verify = cfg.google.insecure_tls_skip_verify
                default_secret_path = cfg.google.client_secret_path
            except Exception:
                pass

        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("setup_dialog_title"))
        dialog.setModal(True)
        dialog.resize(760, 320)

        calendar_input = QLineEdit(default_calendar_id, dialog)
        secret_input = QLineEdit(str(default_secret_path), dialog)
        browse_button = QPushButton(self._t("btn_browse_secret"), dialog)
        browse_button.setObjectName("secondaryAction")

        interval_input = QSpinBox(dialog)
        interval_input.setRange(30, 86_400)
        interval_input.setValue(default_interval)

        insecure_tls_checkbox = QCheckBox(self._t("setup_label_tls"), dialog)
        insecure_tls_checkbox.setChecked(default_insecure_tls_skip_verify)

        secret_row = QHBoxLayout()
        secret_row.addWidget(secret_input, stretch=1)
        secret_row.addWidget(browse_button)
        secret_widget = QWidget(dialog)
        secret_widget.setLayout(secret_row)

        def choose_secret_path() -> None:
            raw_path = secret_input.text().strip()
            current = Path(raw_path).expanduser() if raw_path else default_secret_path
            start_dir = str(current.parent if current.parent.exists() else Path.cwd())
            selected_path, _ = QFileDialog.getOpenFileName(
                dialog,
                self._t("dialog_select_secret"),
                start_dir,
                self._t("dialog_secret_filter"),
            )
            if selected_path:
                secret_input.setText(selected_path)

        browse_button.clicked.connect(choose_secret_path)

        hint_label = QLabel(self._t("setup_hint"), dialog)
        hint_label.setWordWrap(True)
        calendar_help_label = QLabel(self._t("setup_calendar_help_html"), dialog)
        calendar_help_label.setWordWrap(True)
        calendar_help_label.setOpenExternalLinks(True)

        form_layout = QFormLayout()
        form_layout.addRow(self._t("setup_label_calendar_id"), calendar_input)
        form_layout.addRow("", calendar_help_label)
        form_layout.addRow(self._t("setup_label_client_secret"), secret_widget)
        form_layout.addRow(self._t("setup_label_interval"), interval_input)
        form_layout.addRow("", insecure_tls_checkbox)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button is not None:
            ok_button.setText(self._t("setup_save_button"))
        if cancel_button is not None:
            cancel_button.setText(self._t("setup_cancel_button"))
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.addWidget(hint_label)
        layout.addLayout(form_layout)
        layout.addWidget(button_box)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        calendar_id = calendar_input.text().strip()
        if not calendar_id:
            self._show_setup_error(self._t("warning_setup_calendar_required"))
            return

        secret_source_text = secret_input.text().strip()
        if not secret_source_text:
            self._show_setup_error(self._t("warning_setup_secret_required"))
            return

        secret_source_path = Path(secret_source_text).expanduser()
        if not secret_source_path.exists():
            self._show_setup_error(self._t("warning_setup_secret_missing", path=secret_source_path))
            return

        try:
            client_secret_payload = self._parse_client_secret_json(secret_source_path)
            self._validate_desktop_client_secret_json(client_secret_payload)
        except ValueError as exc:
            self._show_setup_error(str(exc))
            return

        interval_seconds = int(interval_input.value())
        insecure_tls_skip_verify = insecure_tls_checkbox.isChecked()
        data_dir = config_path.parent
        data_dir.mkdir(parents=True, exist_ok=True)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        self._append_output(self._t("log_setup_started"))

        destination_secret_path = data_dir / "google_client_secret.json"
        destination_secret_path.write_text(
            json.dumps(client_secret_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._append_output(self._t("log_setup_saved_secret", path=destination_secret_path))

        config_text = self._build_setup_config_toml(
            data_dir=data_dir,
            calendar_id=calendar_id,
            interval_seconds=interval_seconds,
            insecure_tls_skip_verify=insecure_tls_skip_verify,
        )
        config_path.write_text(config_text, encoding="utf-8")
        self._append_output(self._t("log_setup_saved_config", path=config_path))

        self.config_path_input.setText(str(config_path))
        self.interval_input.setValue(interval_seconds)
        self._refresh_config_values(log_errors=True)
        self._refresh_scheduler_status(
            emit_log=False,
            interactive=False,
            show_loading=False,
        )

        self._append_output(self._t("log_setup_done"))
        self._run_doctor()

    def _open_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("settings_dialog_title"))
        dialog.setModal(True)
        dialog.resize(700, 260)

        path_input = QLineEdit(self.config_path_input.text())
        browse_button = QPushButton(self._t("btn_browse_config"))
        browse_button.setObjectName("secondaryAction")

        path_row = QHBoxLayout()
        path_row.addWidget(path_input, stretch=1)
        path_row.addWidget(browse_button)
        path_widget = QWidget(dialog)
        path_widget.setLayout(path_row)

        interval_input = QSpinBox(dialog)
        interval_input.setRange(30, 86_400)
        interval_input.setValue(int(self.interval_input.value()))

        def choose_path() -> None:
            raw_path = path_input.text().strip()
            current = Path(raw_path).expanduser() if raw_path else self._current_config_path()
            start_dir = str(current.parent if current.parent.exists() else default_data_dir())
            selected_path, _ = QFileDialog.getOpenFileName(
                dialog,
                self._t("dialog_select_config"),
                start_dir,
                self._t("dialog_config_filter"),
            )
            if selected_path:
                path_input.setText(selected_path)

        browse_button.clicked.connect(choose_path)

        form_layout = QFormLayout()
        form_layout.addRow(self._t("label_config_file"), path_widget)
        form_layout.addRow(self._t("label_interval"), interval_input)

        hint_label = QLabel(self._t("settings_hint"), dialog)
        hint_label.setWordWrap(True)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button is not None:
            ok_button.setText(self._t("btn_settings_save"))
        if cancel_button is not None:
            cancel_button.setText(self._t("btn_settings_cancel"))
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.addWidget(hint_label)
        layout.addLayout(form_layout)
        layout.addWidget(button_box)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_path = path_input.text().strip()
        if new_path:
            self.config_path_input.setText(new_path)
        self.interval_input.setValue(int(interval_input.value()))
        self._refresh_config_values(log_errors=True)
        self._refresh_scheduler_status(
            emit_log=False,
            interactive=False,
            show_loading=False,
        )

    def _set_command_buttons_enabled(self, enabled: bool) -> None:
        self.setup_assistant_button.setEnabled(enabled)
        self.manual_sync_button.setEnabled(enabled)
        self.doctor_button.setEnabled(enabled)
        self.setup_scheduler_button.setEnabled(enabled)
        self.remove_scheduler_button.setEnabled(enabled)
        self.availability_popup_button.setEnabled(enabled)
        self.refresh_status_button.setEnabled(enabled and not self._scheduler_status_loading)
        self.settings_button.setEnabled(enabled)
        self.open_data_dir_button.setEnabled(enabled)

    def _start_bridgecal_command(self, args: list[str], *, action_key: str) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._finish_action()
            self._append_output(self._t("log_another_running"))
            return

        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(["-m", "bridgecal", *args])
        process.readyReadStandardOutput.connect(self._read_process_stdout)
        process.readyReadStandardError.connect(self._read_process_stderr)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)

        self._process = process
        action_label = self._action_label(action_key)
        quoted = " ".join(shlex.quote(arg) for arg in args)
        self._append_output(self._t("log_starting", action=action_label))
        self._append_output(
            self._t("log_command", command=f"{sys.executable} -m bridgecal {quoted}")
        )
        process.start()

    def _read_process_stdout(self) -> None:
        if self._process is None:
            return
        text = bytes(self._process.readAllStandardOutput()).decode(  # type: ignore[call-overload]
            "utf-8", errors="replace"
        )
        if self._active_action_key == "action_manual_sync":
            for line in text.splitlines():
                if self._try_apply_sync_step_progress(line):
                    continue
                self._try_apply_sync_summary_progress(line)
        self._append_output(text)

    def _read_process_stderr(self) -> None:
        if self._process is None:
            return
        text = bytes(self._process.readAllStandardError()).decode(  # type: ignore[call-overload]
            "utf-8", errors="replace"
        )
        if self._active_action_key == "action_manual_sync":
            for line in text.splitlines():
                if self._try_apply_sync_step_progress(line):
                    continue
                self._try_apply_sync_summary_progress(line)
        self._append_output(text)

    def _on_process_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        completed_action = self._active_action_key
        if exit_code == 0:
            self._append_output(self._t("log_done_success"))
        else:
            self._append_output(self._t("log_done_error", exit_code=exit_code))
        if completed_action == "action_manual_sync":
            if exit_code == 0:
                if self.sync_progress_bar.maximum() == 0:
                    self._set_sync_progress_done()
            else:
                self._set_sync_progress_failed()
        self._finish_action()
        self._process = None
        self._refresh_scheduler_status(
            emit_log=False,
            interactive=False,
            show_loading=False,
        )

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if self._active_action_key == "action_manual_sync":
            self._set_sync_progress_failed()
        self._append_output(self._t("log_process_failure", error=error))
        self._finish_action()
        self._process = None

    def _ensure_config_exists(self) -> Path | None:
        config_path = self._current_config_path()
        if config_path.exists():
            return config_path
        QMessageBox.warning(
            self,
            self._t("warning_config_missing_title"),
            self._t("warning_config_missing_body", path=config_path),
        )
        return None

    def _run_manual_sync(self) -> None:
        config_path = self._ensure_config_exists()
        if config_path is None:
            return
        if not self._begin_action("action_manual_sync"):
            return
        self._set_sync_progress_running()
        self._start_bridgecal_command(
            ["sync", "--once", "--config", str(config_path)],
            action_key="action_manual_sync",
        )

    def _run_doctor(self) -> None:
        config_path = self._ensure_config_exists()
        if config_path is None:
            return
        if not self._begin_action("action_doctor_check"):
            return
        self._start_bridgecal_command(
            ["doctor", "--config", str(config_path)],
            action_key="action_doctor_check",
        )

    def _open_availability_popup(self) -> None:
        config_path = self._ensure_config_exists()
        if config_path is None:
            return
        if self._active_action_key is not None or self._background_thread is not None:
            self._append_output(self._t("log_another_running"))
            return
        self._availability_popup_open = True

        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("availability_dialog_title"))
        dialog.setModal(True)
        dialog.resize(760, 460)

        hint_label = QLabel(self._t("availability_hint"), dialog)
        hint_label.setWordWrap(True)

        input_line = QLineEdit(dialog)
        input_line.setPlaceholderText(self._t("availability_input_placeholder"))
        input_line.setClearButtonEnabled(True)

        model_selector = QComboBox(dialog)
        model_selector.addItem(self._t("availability_model_lfm"), AVAILABILITY_MODEL_IDS[0])
        model_selector.addItem(self._t("availability_model_qwen"), AVAILABILITY_MODEL_IDS[1])
        selected_model_index = model_selector.findData(self._availability_model_id)
        if selected_model_index >= 0:
            model_selector.setCurrentIndex(selected_model_index)

        model_hint_label = QLabel(self._t("availability_model_hint"), dialog)
        model_hint_label.setWordWrap(True)

        status_label = QLabel(dialog)
        self._set_badge(status_label, self._t("availability_status_ready"), tone="neutral")

        busy_indicator = QProgressBar(dialog)
        busy_indicator.setRange(0, 0)
        busy_indicator.setVisible(False)
        busy_indicator.setFormat("")

        result_output = QPlainTextEdit(dialog)
        result_output.setReadOnly(True)
        result_output.setPlainText(self._t("availability_result_waiting"))

        llm_log_label = QLabel(self._t("availability_llm_log_label"), dialog)
        llm_log_output = QPlainTextEdit(dialog)
        llm_log_output.setReadOnly(True)
        llm_log_output.setPlainText(self._t("availability_llm_log_waiting"))
        llm_log_output.setMinimumHeight(150)

        voice_button = QPushButton(self._t("availability_voice_button"), dialog)
        check_button = QPushButton(self._t("availability_check_button"), dialog)
        close_button = QPushButton(self._t("availability_close_button"), dialog)
        voice_button.setObjectName("secondaryAction")
        check_button.setObjectName("primaryAction")
        close_button.setObjectName("secondaryAction")

        popup_state: dict[str, Any] = {
            "busy": False,
            "voice_running": False,
            "voice_stop_requested": False,
            "voice_stop_event": None,
            "llm_stream_queue": None,
            "llm_stream_timer": None,
        }

        def append_llm_log(chunk: str) -> None:
            if not chunk:
                return
            cursor = llm_log_output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            llm_log_output.setTextCursor(cursor)
            llm_log_output.insertPlainText(chunk)
            llm_log_output.ensureCursorVisible()

        def drain_llm_log_queue() -> None:
            stream_queue = popup_state.get("llm_stream_queue")
            if stream_queue is None:
                return
            while True:
                try:
                    chunk = stream_queue.get_nowait()
                except Empty:
                    break
                if isinstance(chunk, str):
                    append_llm_log(chunk)

        def stop_llm_log_stream() -> None:
            stream_timer = popup_state.get("llm_stream_timer")
            if isinstance(stream_timer, QTimer):
                stream_timer.stop()
            drain_llm_log_queue()
            popup_state["llm_stream_queue"] = None
            popup_state["llm_stream_timer"] = None

        def start_llm_log_stream() -> SimpleQueue[str]:
            stop_llm_log_stream()
            llm_log_output.setPlainText("")
            stream_queue: SimpleQueue[str] = SimpleQueue()
            stream_timer = QTimer(dialog)
            stream_timer.timeout.connect(drain_llm_log_queue)
            stream_timer.start(40)
            popup_state["llm_stream_queue"] = stream_queue
            popup_state["llm_stream_timer"] = stream_timer
            return stream_queue

        def refresh_voice_button() -> None:
            if popup_state["voice_running"]:
                voice_button.setText(self._t("availability_voice_button_stop"))
                voice_button.setEnabled(not popup_state["voice_stop_requested"])
            else:
                voice_button.setText(self._t("availability_voice_button"))
                voice_button.setEnabled(not popup_state["busy"])

        def set_popup_busy(
            *,
            busy: bool,
            status_text: str,
            status_tone: str,
            show_indicator: bool,
        ) -> None:
            popup_state["busy"] = busy
            input_line.setEnabled(not busy)
            model_selector.setEnabled(not busy)
            check_button.setEnabled(not busy)
            close_button.setEnabled(not busy)
            self._set_badge(status_label, status_text, tone=status_tone)
            busy_indicator.setVisible(show_indicator)
            refresh_voice_button()

        def set_voice_state(
            *,
            running: bool,
            stop_event: Event | None = None,
            stop_requested: bool = False,
        ) -> None:
            popup_state["voice_running"] = running
            popup_state["voice_stop_requested"] = stop_requested
            popup_state["voice_stop_event"] = stop_event
            refresh_voice_button()

        def request_voice_stop() -> None:
            if not popup_state["voice_running"] or popup_state["voice_stop_requested"]:
                return
            stop_event = popup_state["voice_stop_event"]
            if stop_event is None:
                return
            stop_event.set()
            popup_state["voice_stop_requested"] = True
            self._set_badge(
                status_label,
                self._t("availability_status_stopping"),
                tone="busy",
            )
            refresh_voice_button()

        def on_voice_success(result: object) -> None:
            set_voice_state(running=False)
            if not isinstance(result, str):
                self._finish_action()
                set_popup_busy(
                    busy=False,
                    status_text=self._t("availability_status_error"),
                    status_tone="bad",
                    show_indicator=False,
                )
                QMessageBox.warning(
                    dialog,
                    self._t("warning_availability_title"),
                    self._t(
                        "warning_availability_voice_error",
                        error="Unexpected voice transcription result type.",
                    ),
                )
                return

            transcript = result.strip()
            if transcript:
                input_line.setText(transcript)
                set_popup_busy(
                    busy=False,
                    status_text=self._t("availability_status_ready"),
                    status_tone="good",
                    show_indicator=False,
                )
            else:
                set_popup_busy(
                    busy=False,
                    status_text=self._t("availability_status_error"),
                    status_tone="bad",
                    show_indicator=False,
                )
                QMessageBox.warning(
                    dialog,
                    self._t("warning_availability_title"),
                    self._t("warning_availability_voice_error", error="No speech recognized."),
                )
            self._finish_action()

        def on_voice_failure(error: str) -> None:
            set_voice_state(running=False)
            self._finish_action()
            set_popup_busy(
                busy=False,
                status_text=self._t("availability_status_error"),
                status_tone="bad",
                show_indicator=False,
            )
            QMessageBox.warning(
                dialog,
                self._t("warning_availability_title"),
                self._t("warning_availability_voice_error", error=error),
            )

        def start_voice_input() -> None:
            if popup_state["voice_running"]:
                request_voice_stop()
                return
            if popup_state["busy"]:
                return
            if not self._begin_action("action_voice_input"):
                return
            stop_event = Event()
            set_voice_state(running=True, stop_event=stop_event)
            set_popup_busy(
                busy=True,
                status_text=self._t("availability_status_listening"),
                status_tone="busy",
                show_indicator=True,
            )

            started = self._start_background_operation(
                operation=lambda: self._run_voice_input_operation(
                    language=self._language(),
                    stop_event=stop_event,
                ),
                on_success=on_voice_success,
                on_failure=on_voice_failure,
            )
            if started:
                return
            set_voice_state(running=False)
            set_popup_busy(
                busy=False,
                status_text=self._t("availability_status_error"),
                status_tone="bad",
                show_indicator=False,
            )
            self._finish_action()
            self._append_output(self._t("log_another_running"))

        def on_check_success(result: object) -> None:
            from .availability import AvailabilityResult

            stop_llm_log_stream()
            if not isinstance(result, AvailabilityResult):
                self._finish_action()
                set_popup_busy(
                    busy=False,
                    status_text=self._t("availability_status_error"),
                    status_tone="bad",
                    show_indicator=False,
                )
                QMessageBox.warning(
                    dialog,
                    self._t("warning_availability_title"),
                    self._t(
                        "warning_availability_check_error",
                        error="Unexpected availability result type.",
                    ),
                )
                return

            report = self._format_availability_result_text(result)
            result_output.setPlainText(report)
            if result.available:
                set_popup_busy(
                    busy=False,
                    status_text=self._t("availability_status_available"),
                    status_tone="good",
                    show_indicator=False,
                )
            else:
                set_popup_busy(
                    busy=False,
                    status_text=self._t("availability_status_busy"),
                    status_tone="bad",
                    show_indicator=False,
                )
            self._finish_action()

        def on_check_failure(error: str) -> None:
            stop_llm_log_stream()
            self._finish_action()
            set_popup_busy(
                busy=False,
                status_text=self._t("availability_status_error"),
                status_tone="bad",
                show_indicator=False,
            )
            QMessageBox.warning(
                dialog,
                self._t("warning_availability_title"),
                self._t("warning_availability_check_error", error=error),
            )

        def start_availability_check() -> None:
            if popup_state["busy"]:
                return
            query_text = input_line.text().strip()
            if not query_text:
                QMessageBox.warning(
                    dialog,
                    self._t("warning_availability_title"),
                    self._t("warning_availability_query_required"),
                )
                return
            if not self._begin_action("action_availability_check"):
                return
            selected_model = model_selector.currentData()
            model_id = (
                selected_model
                if isinstance(selected_model, str) and selected_model in AVAILABILITY_MODEL_IDS
                else AVAILABILITY_MODEL_IDS[0]
            )
            self._availability_model_id = model_id
            stream_queue = start_llm_log_stream()
            set_popup_busy(
                busy=True,
                status_text=self._t("availability_status_checking"),
                status_tone="busy",
                show_indicator=True,
            )
            started = self._start_background_operation(
                operation=lambda: self._run_availability_check_operation(
                    config_path=config_path,
                    query_text=query_text,
                    language=self._language(),
                    model_id=model_id,
                    on_parser_chunk=stream_queue.put,
                ),
                on_success=on_check_success,
                on_failure=on_check_failure,
            )
            if started:
                return
            stop_llm_log_stream()
            set_popup_busy(
                busy=False,
                status_text=self._t("availability_status_error"),
                status_tone="bad",
                show_indicator=False,
            )
            self._finish_action()
            self._append_output(self._t("log_another_running"))

        def close_popup() -> None:
            if popup_state["busy"]:
                return
            dialog.accept()

        action_row = QHBoxLayout()
        action_row.addWidget(voice_button)
        action_row.addWidget(check_button)
        action_row.addWidget(close_button)

        form = QFormLayout()
        form.addRow(self._t("availability_model_label"), model_selector)
        form.addRow(self._t("availability_input_label"), input_line)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.addWidget(hint_label)
        layout.addLayout(form)
        layout.addWidget(model_hint_label)
        layout.addLayout(action_row)
        layout.addWidget(status_label)
        layout.addWidget(busy_indicator)
        layout.addWidget(llm_log_label)
        layout.addWidget(llm_log_output, stretch=1)
        layout.addWidget(result_output, stretch=1)

        voice_button.clicked.connect(start_voice_input)
        check_button.clicked.connect(start_availability_check)
        close_button.clicked.connect(close_popup)
        input_line.returnPressed.connect(start_availability_check)

        try:
            dialog.exec()
        finally:
            stop_llm_log_stream()
            self._availability_popup_open = False

    def _run_availability_check_operation(
        self,
        *,
        config_path: Path,
        query_text: str,
        language: str,
        model_id: str,
        on_parser_chunk: Callable[[str], None] | None = None,
    ) -> AvailabilityResult:
        from .availability import check_availability, parse_natural_time_range
        from .google_client import GoogleClient
        from .outlook_client import OutlookClient

        cfg = load_config(config_path)
        query_range = parse_natural_time_range(
            query_text,
            preferred_language=language if language in {LANG_JA, LANG_EN} else LANG_JA,
            model_id=model_id,
            max_new_tokens=AVAILABILITY_MAX_NEW_TOKENS,
            force_thinking=True,
            on_model_output_chunk=on_parser_chunk,
        )

        outlook_events = list(OutlookClient().list_events(query_range.start, query_range.end))
        google_events = list(
            GoogleClient(
                calendar_id=cfg.google.calendar_id,
                client_secret_path=cfg.google.client_secret_path,
                token_path=cfg.google.token_path,
                insecure_tls_skip_verify=cfg.google.insecure_tls_skip_verify,
            ).list_events(query_range.start, query_range.end)
        )
        return check_availability(
            query_text=query_text,
            query_range=query_range,
            outlook_events=outlook_events,
            google_events=google_events,
        )

    def _run_voice_input_operation(
        self,
        *,
        language: str,
        stop_event: Event | None = None,
    ) -> str:
        from .voice_stt import transcribe_microphone

        stt_language = "ja" if language == LANG_JA else "en"
        return transcribe_microphone(
            language=stt_language,
            seconds=7.0,
            stop_event=stop_event,
        )

    def _format_availability_result_text(self, result: AvailabilityResult) -> str:
        lines: list[str] = [
            self._t(
                "availability_result_window",
                start=self._format_availability_time(result.query_range.start),
                end=self._format_availability_time(result.query_range.end),
            )
        ]
        if result.available:
            lines.append(self._t("availability_result_free"))
            return "\n".join(lines)

        lines.append(self._t("availability_result_busy", count=len(result.conflicts)))
        for conflict in result.conflicts:
            start_label, end_label = self._format_conflict_time_range(conflict)
            summary = conflict.summary.strip() or self._t("availability_summary_empty")
            lines.append(
                self._t(
                    "availability_result_conflict",
                    source=self._availability_source_label(conflict.origin),
                    start=start_label,
                    end=end_label,
                    summary=summary,
                )
            )
        return "\n".join(lines)

    def _format_conflict_time_range(self, conflict: AvailabilityConflict) -> tuple[str, str]:
        if conflict.all_day:
            return (
                f"{conflict.start.strftime('%Y-%m-%d')} {self._t('availability_result_all_day')}",
                f"{conflict.end.strftime('%Y-%m-%d')} {self._t('availability_result_all_day')}",
            )
        return (
            self._format_availability_time(conflict.start),
            self._format_availability_time(conflict.end),
        )

    def _format_availability_time(self, value: datetime) -> str:
        local_value = value.astimezone() if value.tzinfo is not None else value
        return local_value.strftime("%Y-%m-%d %H:%M")

    def _availability_source_label(self, origin: str) -> str:
        if origin == "outlook":
            return self._t("availability_source_outlook")
        return self._t("availability_source_google")

    def _setup_scheduler(self) -> None:
        config_path = self._ensure_config_exists()
        if config_path is None:
            return

        if not self._begin_action("action_auto_on"):
            return
        interval_seconds = int(self.interval_input.value())
        action_label = self._action_label("action_auto_on")
        self._append_output(self._t("log_starting", action=action_label))

        started = self._start_background_operation(
            operation=lambda: configure_scheduler_with_elevation(
                config_path=config_path,
                interval_seconds=interval_seconds,
            ),
            on_success=self._on_setup_scheduler_finished,
            on_failure=self._on_scheduler_operation_failed,
        )
        if not started:
            self._append_output(self._t("log_another_running"))
            self._finish_action()

    def _remove_scheduler(self) -> None:
        if not self._begin_action("action_auto_off"):
            return
        action_label = self._action_label("action_auto_off")
        self._append_output(self._t("log_starting", action=action_label))

        started = self._start_background_operation(
            operation=remove_scheduler_with_elevation,
            on_success=self._on_remove_scheduler_finished,
            on_failure=self._on_scheduler_operation_failed,
        )
        if not started:
            self._append_output(self._t("log_another_running"))
            self._finish_action()

    def _refresh_scheduler_status_from_button(self) -> None:
        self._refresh_scheduler_status(
            emit_log=True,
            interactive=True,
            show_loading=True,
        )

    def _schedule_async_scheduler_status_refresh(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self._refresh_scheduler_status(
                emit_log=True,
                interactive=False,
                show_loading=False,
            ),
        )

    def _refresh_scheduler_status(
        self,
        *,
        emit_log: bool,
        interactive: bool,
        show_loading: bool,
    ) -> None:
        if not interactive and self._availability_popup_open:
            return

        if self._scheduler_status_loading:
            if interactive:
                self._append_output(self._t("log_another_running"))
            return

        if self._background_thread is not None:
            if interactive:
                self._append_output(self._t("log_another_running"))
            return

        if interactive:
            if not self._begin_action("action_refresh_status"):
                return
            self._append_output(
                self._t("log_starting", action=self._action_label("action_refresh_status"))
            )
        elif self._active_action_key is not None:
            return

        started = self._start_background_operation(
            operation=query_scheduler_status,
            on_success=lambda result: self._on_scheduler_status_fetched(
                status=str(result),
                emit_log=emit_log,
                interactive=interactive,
            ),
            on_failure=lambda error: self._on_scheduler_status_fetch_failed(
                error=error,
                interactive=interactive,
            ),
        )
        if started and show_loading:
            self._set_scheduler_loading(True)
            return
        if not started and interactive:
            self._append_output(self._t("log_another_running"))
            self._finish_action()

    def _on_setup_scheduler_finished(self, result: object) -> None:
        if not isinstance(result, SchedulerOperationResult):
            self._append_output(
                self._t("log_auto_on_fail", message="Unexpected scheduler operation result.")
            )
            self._finish_action()
            self._schedule_async_scheduler_status_refresh()
            return

        if result.ok:
            self._append_output(self._t("log_auto_on_success", message=result.message))
        else:
            self._append_output(self._t("log_auto_on_fail", message=result.message))
        self._finish_action()
        self._schedule_async_scheduler_status_refresh()

    def _on_remove_scheduler_finished(self, result: object) -> None:
        if not isinstance(result, SchedulerOperationResult):
            self._append_output(
                self._t("log_auto_off_fail", message="Unexpected scheduler operation result.")
            )
            self._finish_action()
            self._schedule_async_scheduler_status_refresh()
            return

        if result.ok:
            self._append_output(self._t("log_auto_off_success", message=result.message))
        else:
            self._append_output(self._t("log_auto_off_fail", message=result.message))
        self._finish_action()
        self._schedule_async_scheduler_status_refresh()

    def _on_scheduler_operation_failed(self, error: str) -> None:
        if self._active_action_key == "action_auto_on":
            self._append_output(self._t("log_auto_on_fail", message=error))
        elif self._active_action_key == "action_auto_off":
            self._append_output(self._t("log_auto_off_fail", message=error))
        else:
            self._append_output(self._t("log_process_failure", error=error))
        self._finish_action()
        self._schedule_async_scheduler_status_refresh()

    def _on_scheduler_status_fetched(
        self,
        *,
        status: str,
        emit_log: bool,
        interactive: bool,
    ) -> None:
        self._set_scheduler_loading(False)
        status_changed = status != self._last_scheduler_status
        self._last_scheduler_status = status
        self._apply_scheduler_status(status, status_changed=status_changed, emit_log=emit_log)
        if interactive:
            self._finish_action()

    def _on_scheduler_status_fetch_failed(self, *, error: str, interactive: bool) -> None:
        self._set_scheduler_loading(False)
        status = f"Unknown ({error})"
        status_changed = status != self._last_scheduler_status
        self._last_scheduler_status = status
        self._apply_scheduler_status(status, status_changed=status_changed, emit_log=True)
        self._append_output(self._t("log_status_refresh_fail", error=error))
        if interactive:
            self._finish_action()

    def _apply_scheduler_status(
        self,
        status: str,
        *,
        status_changed: bool,
        emit_log: bool,
    ) -> None:
        if status.startswith("Configured"):
            self._set_badge(self.scheduler_status, self._t("status_auto_on"), tone="good")
            if emit_log and status_changed:
                self._append_output(self._t("log_status_on"))
            return
        if status == "Not configured":
            self._set_badge(self.scheduler_status, self._t("status_auto_off"), tone="neutral")
            if emit_log and status_changed:
                self._append_output(self._t("log_status_off"))
            return
        self._set_badge(self.scheduler_status, self._t("status_auto_unknown"), tone="bad")
        if emit_log and status_changed:
            self._append_output(self._t("log_status_error", status=status))

    def _on_language_changed(self) -> None:
        self._apply_language()
        # Re-render current statuses using cached values; avoid filesystem/PowerShell work.
        self._set_badge(
            self.config_status, self._t(self._config_status_key), tone=self._config_status_tone
        )
        if self._scheduler_status_loading:
            self._set_badge(self.scheduler_status, self._t("status_auto_loading"), tone="busy")
            return
        if self._last_scheduler_status is None:
            self._set_badge(self.scheduler_status, self._t("status_auto_unknown"), tone="bad")
            return
        self._apply_scheduler_status(
            self._last_scheduler_status,
            status_changed=False,
            emit_log=False,
        )

    def _open_data_dir(self) -> None:
        config_path = self._current_config_path()
        target = config_path.parent
        if config_path.exists():
            try:
                cfg = load_config(config_path)
                target = cfg.data_dir
            except Exception:
                pass
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


def launch_gui(config_path: Path | None = None) -> int:
    if sys.platform != "win32":
        raise RuntimeError("BridgeCal GUI is available on Windows only.")

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)

    window = BridgeCalWindow(config_path=config_path)
    window.show()
    if owns_app:
        return int(app.exec())
    return 0
