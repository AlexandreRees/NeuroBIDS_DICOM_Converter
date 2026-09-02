"""Qt stylesheets — compact professional scientific UI."""

APP_STYLESHEET = """
QWidget {
    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 12px;
    color: #1f2933;
}

QMainWindow {
    background: #eef2f6;
}

QFrame#navPanel {
    background: #1b2a3a;
    border-right: 1px solid #102230;
}

QLabel#navBrand {
    color: #f0f4f8;
    font-size: 14px;
    font-weight: 700;
}

QLabel#navSubtitle {
    color: #9fb3c8;
    font-size: 11px;
}

QLabel#navSection {
    color: #829ab1;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.6px;
    padding: 10px 12px 2px 12px;
}

QLabel#monoLabel {
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px;
    color: #243b53;
}

QLabel#pageKicker {
    color: #627d98;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.4px;
}

QLabel#subtitleLabel {
    color: #486581;
    font-size: 12px;
}

QLabel#statusPass {
    color: #276749;
    font-weight: 700;
}

QLabel#statusReview {
    color: #975a16;
    font-weight: 700;
}

QLabel#statusFail {
    color: #9b2c2c;
    font-weight: 700;
}

QLabel#statusInfo {
    color: #2a4365;
    font-weight: 700;
}

QFrame#inspectorPanel {
    background: #ffffff;
    border: 1px solid #d9e2ec;
    border-radius: 6px;
}

QFrame#unavailableBanner {
    background: #f7fafc;
    border: 1px solid #d9e2ec;
    border-radius: 4px;
}

QFrame#statCard {
    background: #ffffff;
    border: 1px solid #d9e2ec;
    border-radius: 6px;
}

QFrame#statusBarFrame {
    background: #f7fafc;
    border-top: 1px solid #d9e2ec;
}

QPushButton#chipButton {
    background: #f0f4f8;
    border: 1px solid #d9e2ec;
    border-radius: 4px;
    padding: 5px 10px;
    text-align: left;
    font-weight: 500;
    color: #243b53;
}

QPushButton#chipButton:hover {
    background: #e4ebf2;
    border-color: #9fb3c8;
}

QPushButton#ghostButton {
    background: transparent;
    border: 1px solid #9fb3c8;
    color: #243b53;
}

QLabel#statValue {
    font-size: 22px;
    font-weight: 700;
    color: #102a43;
}

QLabel#statCaption {
    color: #627d98;
    font-size: 11px;
    font-weight: 600;
}

QSplitter::handle {
    background: #d9e2ec;
    width: 4px;
    height: 4px;
}

QPushButton#navButton {
    background: transparent;
    color: #d9e2ec;
    border: none;
    border-radius: 6px;
    text-align: left;
    padding: 9px 12px;
    font-weight: 600;
}

QPushButton#navButton:hover {
    background: #243b53;
    color: #ffffff;
}

QPushButton#navButton:checked {
    background: #334e68;
    color: #ffffff;
}

QGroupBox {
    font-weight: 600;
    border: 1px solid #d9e2ec;
    border-radius: 6px;
    margin-top: 10px;
    padding: 12px 10px 8px 10px;
    background: #ffffff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #334e68;
}

QLineEdit {
    border: 1px solid #bcccdc;
    border-radius: 4px;
    padding: 5px 8px;
    background: #ffffff;
    selection-background-color: #486581;
    min-height: 18px;
}

QLineEdit:focus {
    border: 1px solid #486581;
}

QPushButton {
    border: 1px solid #9fb3c8;
    border-radius: 4px;
    padding: 5px 10px;
    background: #ffffff;
    min-height: 18px;
}

QPushButton:hover {
    background: #f0f4f8;
}

QPushButton:pressed {
    background: #d9e2ec;
}

QPushButton#primaryButton {
    background: #243b53;
    color: #ffffff;
    border: 1px solid #102a43;
    font-weight: 600;
    min-width: 110px;
    padding: 7px 14px;
}

QPushButton#primaryButton:hover {
    background: #334e68;
}

QPushButton#dangerButton {
    background: #ffffff;
    color: #9b2c2c;
    border: 1px solid #c53030;
    font-weight: 600;
    min-width: 110px;
    padding: 7px 14px;
}

QPushButton#dangerButton:hover {
    background: #fff5f5;
}

QPushButton#dangerButton:disabled {
    color: #c4a8a8;
    border-color: #e2c8c8;
}

QFrame#proposalBanner {
    background: #fffbeb;
    border: 1px solid #f6e05e;
    border-radius: 4px;
}

QFrame#stateBanner {
    background: #f7fafc;
    border: 1px solid #d9e2ec;
    border-radius: 4px;
}

QTextEdit#copilotConversation {
    background: #f7fafc;
    border: 1px solid #d9e2ec;
    border-radius: 4px;
    padding: 6px;
}

QGroupBox#proposalBox {
    border: 1px solid #d69e2e;
    background: #fffdf7;
}

QSplitter::handle:horizontal {
    background: #bcccdc;
    width: 6px;
}

QToolButton#collapsibleToggle {
    background: #f0f4f8;
    border: 1px solid #d9e2ec;
    border-radius: 4px;
    padding: 6px 8px;
    font-weight: 600;
    color: #243b53;
    text-align: left;
}

QToolButton#collapsibleToggle:hover {
    background: #e4ebf2;
}

QFrame#collapsibleBody {
    background: #ffffff;
    border: 1px solid #e4e7eb;
    border-top: none;
    border-bottom-left-radius: 4px;
    border-bottom-right-radius: 4px;
}

QCheckBox {
    spacing: 6px;
    padding: 2px 0;
}

QRadioButton {
    spacing: 6px;
    padding: 2px 0;
}

QProgressBar {
    border: 1px solid #bcccdc;
    border-radius: 4px;
    text-align: center;
    background: #ffffff;
    height: 16px;
}

QProgressBar::chunk {
    background: #486581;
    border-radius: 3px;
}

QTableWidget {
    border: 1px solid #d9e2ec;
    border-radius: 4px;
    background: #ffffff;
    gridline-color: #e4e7eb;
    selection-background-color: #d9e2ec;
    selection-color: #102a43;
}

QHeaderView::section {
    background: #f0f4f8;
    border: none;
    border-bottom: 1px solid #d9e2ec;
    border-right: 1px solid #e4e7eb;
    padding: 6px;
    font-weight: 600;
    color: #334e68;
}

QLabel#statusLabel {
    color: #486581;
}

QLabel#titleLabel {
    font-size: 16px;
    font-weight: 700;
    color: #102a43;
}

QPlainTextEdit#logView {
    background: #102a43;
    color: #e0e7ef;
    border: 1px solid #243b53;
    border-radius: 4px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px;
}

QScrollArea {
    border: none;
    background: transparent;
}

QListWidget {
    border: 1px solid #d9e2ec;
    border-radius: 4px;
    background: #ffffff;
}
"""
