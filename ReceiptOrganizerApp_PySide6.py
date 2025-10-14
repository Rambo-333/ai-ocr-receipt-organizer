import sys
import os
import threading
import logging
import json
import logging.config
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QComboBox, QProgressBar, QTextEdit, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QTextCursor, QFont
from datetime import datetime
from ReceiptOrganizerExecutor import Executor
from typing import Optional

GOLDEN_RATIO = 1.618

class QtLogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal
    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)

class SignalProxy(QObject):
    log_signal = Signal(str)
    progress_max_signal = Signal(int)
    progress_add_signal = Signal(int)
    complete_signal = Signal()
    abort_complete_signal = Signal()

class ReceiptOrganizerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.progress_timer: Optional[QTimer] = None
        self.is_aborting = False
        self._setup_logging_config()
        self.setWindowTitle("ReceiptOrganizer")
        self.setMinimumSize(800, 680)

        # 画面サイズに応じて適切なウィンドウサイズを設定
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            # 画面の40%のサイズを使用（コンパクトに）
            width = max(800, min(900, int(screen_geometry.width() * 0.4)))
            height = max(680, min(750, int(screen_geometry.height() * 0.6)))
            self.resize(width, height)

            # ウィンドウを画面中央に配置
            self.move(
                (screen_geometry.width() - width) // 2,
                (screen_geometry.height() - height) // 2
            )
        else:
            # フォールバック
            self.resize(850, 720)

        self.setStyleSheet(self._get_stylesheet())
        self._init_ui()
        self.executor = None
        self.worker_thread = None
        self.progress_max = 0
        self.progress_val = 0
        self.signal_proxy = SignalProxy()
        self.signal_proxy.log_signal.connect(self._append_log)
        self.signal_proxy.progress_max_signal.connect(self._set_progress_max)
        self.signal_proxy.progress_add_signal.connect(self._add_progress)
        self.signal_proxy.complete_signal.connect(self._on_complete)
        self.signal_proxy.abort_complete_signal.connect(self._on_abort_complete)
        self._setup_logger()
        self._set_buttons_state(start=True, stop=False)

    def _setup_logging_config(self):
        config_path = os.path.join(os.path.dirname(__file__), 'log_config.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    log_conf = json.load(f)
                logging.config.dictConfig(log_conf)
            except Exception as e:
                logging.basicConfig(level=logging.INFO)
                logging.error(f"ログ設定ファイルの読み込みに失敗しました: {e}")
        # 存在しない場合や失敗時はデフォルト設定で続行

    def _init_ui(self):
        self.main_layout = QVBoxLayout()
        main_layout = self.main_layout
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(32, 28, 32, 32)

        # タイトル（シンプルに）
        title_frame = QFrame()
        title_frame.setObjectName("TitleCard")
        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 16, 0, 16)
        logo_label = QLabel("ReceiptOrganizer")
        logo_label.setObjectName("LogoLabel")
        logo_label.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        logo_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        catch_label = QLabel("請求書を自動で仕分けします")
        catch_label.setObjectName("CatchLabel")
        catch_label.setFont(QFont("Segoe UI", 13))
        catch_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title_layout.addWidget(logo_label)
        title_layout.addWidget(catch_label)
        title_frame.setLayout(title_layout)
        main_layout.addWidget(title_frame)

        # メインカード
        card_frame = QFrame()
        card_frame.setObjectName("MainCard")
        card_layout = QVBoxLayout()
        card_layout.setSpacing(0)
        card_layout.setContentsMargins(24, 24, 24, 24)

        # フォルダ選択
        folder_label = QLabel("フォルダ選択")
        folder_label.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        card_layout.addWidget(folder_label)
        card_layout.addSpacing(8)

        folder_input_layout = QHBoxLayout()
        folder_input_layout.setSpacing(10)
        self.folder_path_label = QLabel("フォルダを選択してください")
        self.folder_path_label.setObjectName("FolderPath")
        self.folder_path_label.setFixedHeight(40)
        folder_btn = QPushButton("参照")
        folder_btn.setObjectName("BrowseButton")
        folder_btn.clicked.connect(self._select_folder)
        folder_btn.setFixedSize(90, 40)
        self.folder_btn = folder_btn
        folder_input_layout.addWidget(self.folder_path_label, 1)
        folder_input_layout.addWidget(folder_btn, 0)
        card_layout.addLayout(folder_input_layout)
        card_layout.addSpacing(24)

        # 年月選択
        date_label = QLabel("年月選択")
        date_label.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        card_layout.addWidget(date_label)
        card_layout.addSpacing(8)

        date_layout = QHBoxLayout()
        date_layout.setSpacing(8)
        now = datetime.now()
        self.year_combo = QComboBox()
        self.year_combo.addItems([str(y) for y in range(2000, 2100)])
        self.year_combo.setCurrentText(str(now.year))
        self.year_combo.setFixedSize(110, 40)

        year_label = QLabel("年")
        year_label.setFont(QFont("Segoe UI", 12))

        self.month_combo = QComboBox()
        self.month_combo.addItems([str(m) for m in range(1, 13)])
        self.month_combo.setCurrentText(str(now.month))
        self.month_combo.setFixedSize(90, 40)

        month_label = QLabel("月")
        month_label.setFont(QFont("Segoe UI", 12))

        date_layout.addWidget(self.year_combo, 0)
        date_layout.addWidget(year_label, 0)
        date_layout.addWidget(self.month_combo, 0)
        date_layout.addWidget(month_label, 0)
        date_layout.addStretch(1)
        card_layout.addLayout(date_layout)
        card_layout.addSpacing(24)

        # 開始・中止ボタン
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.start_btn = QPushButton("開始")
        self.start_btn.setObjectName("StartButton")
        self.start_btn.setFixedSize(80, 36)
        self.stop_btn = QPushButton("中止")
        self.stop_btn.setObjectName("StopButton")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setFixedSize(80, 36)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        btn_layout.addWidget(self.start_btn, 0)
        btn_layout.addWidget(self.stop_btn, 0)
        btn_layout.addStretch(1)
        card_layout.addLayout(btn_layout)

        card_frame.setLayout(card_layout)
        main_layout.addWidget(card_frame)

        # 進捗バー
        progress_frame = QFrame()
        progress_frame.setObjectName("ProgressCard")
        progress_layout = QVBoxLayout()
        progress_layout.setContentsMargins(24, 20, 24, 20)
        progress_layout.setSpacing(10)

        self.progress_detail = QLabel("進捗：0/0 ファイル")
        self.progress_detail.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self.progress_detail.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(32)

        progress_layout.addWidget(self.progress_detail)
        progress_layout.addWidget(self.progress_bar)
        progress_frame.setLayout(progress_layout)
        main_layout.addWidget(progress_frame)

        # ログ表示
        log_frame = QFrame()
        log_frame.setObjectName("LogCard")
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(24, 16, 24, 16)
        log_layout.setSpacing(8)

        log_label = QLabel("ログ")
        log_label.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("LogText")
        self.log_text.setFixedHeight(140)

        log_layout.addWidget(log_label)
        log_layout.addWidget(self.log_text)
        log_frame.setLayout(log_layout)
        main_layout.addWidget(log_frame)

        self.setLayout(main_layout)

    def _setup_logger(self):
        self.logger = logging.getLogger("ReceiptOrganizerApp_PySide6")
        self.logger.setLevel(logging.INFO)
        handler = QtLogHandler(self.signal_proxy.log_signal)
        formatter = logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s", "%H:%M:%S")
        handler.setFormatter(formatter)
        self.logger.handlers.clear()
        self.logger.addHandler(handler)

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder:
            self.folder_path_label.setText(folder)

    def _on_start(self):
        folder = self.folder_path_label.text()
        year = self.year_combo.currentText()
        month = self.month_combo.currentText()
        if not folder or folder == "フォルダを選択してください":
            self._append_log("[ERROR] フォルダが選択されていません。")
            self._set_buttons_state(start=True, stop=False)
            return
        if not os.path.isdir(folder):
            self._append_log("[ERROR] 有効なフォルダを選択してください。")
            self._set_buttons_state(start=True, stop=False)
            return
        if not (year and month):
            self._append_log("[ERROR] 年月が正しく選択されていません。")
            self._set_buttons_state(start=True, stop=False)
            return
        self._set_buttons_state(start=False, stop=True)
        self.progress_bar.setValue(0)
        self.progress_detail.setText("進捗：0/0 ファイル")
        self.log_text.clear()
        # Executorの初期化
        try:
            self.executor = Executor(self.logger)
            self.executor.set_event_max_progress(self.signal_proxy.progress_max_signal.emit)
            self.executor.set_event_add_progress(self.signal_proxy.progress_add_signal.emit)
            self.executor.set_event_abort_complete(self.signal_proxy.abort_complete_signal.emit)
        except (FileNotFoundError, ValueError) as e:
            self._append_log(f"[ERROR] 初期化エラー: {e}")
            self._set_buttons_state(start=True, stop=False)
            return
        # 別スレッドで実行
        self.worker_thread = threading.Thread(target=self._run_executor, args=(folder, f"{year}{int(month):02d}"))
        self.worker_thread.start()
        # タイマーはここでは起動しない

    def _run_executor(self, folder, date_str):
        try:
            assert self.executor is not None
            self.executor.start(folder, date_str, max_workers=4)
        except Exception as e:
            self.signal_proxy.log_signal.emit(f"[ERROR] {e}")
        finally:
            if self.progress_max != 0:
                self.signal_proxy.progress_add_signal.emit(0)
                self._set_buttons_state(start=True, stop=False)

    def _on_stop(self):
        if self.executor:
            self.is_aborting = True
            self.executor.abort()
            self._append_log("[INFO] 中止要求を送信しました。")

    def _set_buttons_state(self, start, stop):
        self.start_btn.setEnabled(start)
        self.stop_btn.setEnabled(stop)
        # 参照ボタンも完了・中止時はグレーアウト
        if not (start or stop):
            self.folder_btn.setEnabled(False)
            self.folder_btn.setStyleSheet("background: #e0e0e0; color: #aaa; opacity: 0.7;")
            self.log_text.setStyleSheet("background: #e0e0e0; color: #aaa; opacity: 0.7;")  # グレーアウト風
            self.log_text.setEnabled(True)  # 常に有効化
        else:
            self.folder_btn.setEnabled(True)
            self.folder_btn.setStyleSheet("")
            self.log_text.setStyleSheet("")  # 通常色
            self.log_text.setEnabled(True)  # 常に有効化
        if start:
            self.start_btn.setStyleSheet("")
        else:
            self.start_btn.setStyleSheet("background: #e0e0e0; color: #aaa;")
        if stop:
            self.stop_btn.setStyleSheet("")
        else:
            self.stop_btn.setStyleSheet("background: #e0e0e0; color: #aaa;")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        # if hasattr(self, 'main_layout'):
        #     self.main_layout.activate()
        # self.adjustSize()

    def _set_progress_max(self, max_val):
        self.progress_max = max_val
        self.progress_val = 0
        # max_valが0の場合、ビジーインジケータが動くのを防ぐため、最大値を1に設定
        self.progress_bar.setMaximum(max_val if max_val > 0 else 1)
        self.progress_bar.setValue(0)
        self.progress_detail.setText(f"進捗：0/{max_val} ファイル")

        if max_val == 0:
            # 対象ファイルがない場合、ログを出力してボタンの状態を戻す
            self.signal_proxy.log_signal.emit("[INFO] 対象となるPDFファイルが見つかりませんでした。")
            self._set_buttons_state(start=True, stop=False)
            if self.progress_timer is not None:
                self.progress_timer.stop()
            return

        # progress_maxがセットされたタイミングで監視タイマーを起動
        self._start_progress_timer()

    def _add_progress(self, value):
        self.progress_val += value
        self.progress_bar.setValue(self.progress_val)
        self.progress_detail.setText(f"進捗：{self.progress_val}/{self.progress_max} ファイル")
        if self.progress_val >= self.progress_max and self.progress_max > 0:
            # 完了時は進捗監視タイマーも止める
            if self.progress_timer is not None:
                self.progress_timer.stop()
            self.signal_proxy.complete_signal.emit()

    def _append_log(self, msg):
        from PySide6.QtCore import QTimer
        def do_append():
            self.log_text.append(msg)
            self.log_text.moveCursor(QTextCursor.MoveOperation.End)
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            self.log_text.repaint()
        QTimer.singleShot(0, do_append)

    def _start_progress_timer(self):
        if self.progress_timer is not None:
            self.progress_timer.stop()
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self._check_executor_status)
        if self.progress_timer is not None:
            self.progress_timer.start(500)  # type: ignore

    def _check_executor_status(self):
        # progress_maxが0なら、まだ処理開始前なのでボタン状態を戻さない
        if self.executor and not self.executor.is_running():
            if self.progress_max == 0:
                # 何もせずreturn（ボタン状態は変えない）
                return
            if self.is_aborting:
                # 中止処理中はボタン状態を変更しない
                return
            self._set_buttons_state(start=True, stop=False)
            if self.progress_timer is not None:
                self.progress_timer.stop()

    def _on_complete(self):
        # 完了時の処理
        self._append_log("[INFO] すべての処理が完了しました。")
        self._set_buttons_state(start=False, stop=False)
        self.executor = None

    def _on_abort_complete(self):
        self.is_aborting = False
        msg = "[INFO] 処理を中止しました。"
        self._append_log(msg)
        # ボタン両方グレーアウト
        self._set_buttons_state(start=False, stop=False)
        # 進捗バー・詳細をリセット
        self.progress_bar.setValue(0)
        self.progress_detail.setText("進捗：0/0 ファイル")
        # タイマー停止
        if self.progress_timer is not None:
            self.progress_timer.stop()
        # Executorもリセット
        self.executor = None

    def _get_stylesheet(self):
        # モダンでシンプルなデザイン（Linear/Vercel風）
        return """
        QWidget {
            background: #fafafa;
            font-family: 'Segoe UI', 'SF Pro Display', 'Inter', sans-serif;
            font-size: 14px;
            color: #171717;
        }
        #TitleCard {
            background: transparent;
            border: none;
        }
        #LogoLabel {
            color: #0a0a0a;
        }
        #CatchLabel {
            color: #737373;
        }
        #MainCard {
            background: #ffffff;
            border-radius: 8px;
            border: 1px solid #e5e5e5;
        }
        #ProgressCard {
            background: #ffffff;
            border-radius: 8px;
            border: 1px solid #e5e5e5;
        }
        #LogCard {
            background: #ffffff;
            border-radius: 8px;
            border: 1px solid #e5e5e5;
        }
        #FolderPath {
            background: #fafafa;
            border: 1px solid #e5e5e5;
            border-radius: 6px;
            padding: 0 12px;
            color: #525252;
            font-size: 13px;
        }
        #BrowseButton {
            background: #0a0a0a;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            padding: 0 20px;
        }
        #BrowseButton:hover {
            background: #262626;
        }
        #BrowseButton:disabled {
            background: #e5e5e5;
            color: #a3a3a3;
        }
        #StartButton {
            background: #0a0a0a;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            padding: 0 24px;
        }
        #StartButton:hover {
            background: #262626;
        }
        #StartButton:disabled {
            background: #e5e5e5;
            color: #a3a3a3;
        }
        #StopButton {
            background: #ffffff;
            color: #0a0a0a;
            border: 1px solid #e5e5e5;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            padding: 0 24px;
        }
        #StopButton:hover {
            background: #fafafa;
            border-color: #d4d4d4;
        }
        #StopButton:disabled {
            background: #fafafa;
            color: #d4d4d4;
            border-color: #f5f5f5;
        }
        QComboBox {
            background: #ffffff;
            border: 1px solid #e5e5e5;
            border-radius: 6px;
            padding: 0 12px;
            font-size: 13px;
            color: #171717;
        }
        QComboBox:hover {
            border-color: #d4d4d4;
        }
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        QProgressBar {
            border: 1px solid #e5e5e5;
            border-radius: 6px;
            background: #fafafa;
            text-align: center;
            font-size: 12px;
            font-weight: 500;
            color: #525252;
        }
        QProgressBar::chunk {
            background: #0a0a0a;
            border-radius: 5px;
        }
        #LogText {
            font-family: 'Consolas', 'SF Mono', 'Monaco', monospace;
            font-size: 12px;
            background: #fafafa;
            border: 1px solid #e5e5e5;
            border-radius: 6px;
            padding: 12px;
            color: #262626;
            line-height: 1.6;
        }
        """

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = ReceiptOrganizerApp()
    win.show()
    sys.exit(app.exec())