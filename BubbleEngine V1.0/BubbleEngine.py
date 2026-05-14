with open(r"C:\Users\Public\be_start.log", "w") as f:
    f.write("script started\n")

import sys
import os
import winreg
from urllib.parse import urlparse, quote_plus
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLineEdit, QPushButton, QTabWidget, QHBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineScript
from PyQt6.QtCore import QUrl, QSize, Qt, QObject, QEvent
from PyQt6.QtGui import QIcon, QFont, QPixmap, QPainter, QColor, QSurfaceFormat
from PyQt6.QtWidgets import QTabBar
from PyQt6.QtGui import QPen

if "__compiled__" in dir():
    BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
elif getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ROUTES_FILE = os.path.join(BASE_DIR, ".routes")
START_PAGE_FILE = os.path.join(BASE_DIR, ".start_page")
SEARCH_FILE = os.path.join(BASE_DIR, ".search")

if "__compiled__" in dir():
    ICONS_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "Libs", "icons")
else:
    ICONS_PATH = os.path.join(BASE_DIR, "icons")

def parse_args():
    flags = set()
    config = {}
    urls = []
    for arg in sys.argv[1:]:
        if arg.startswith("--disable:"):
            flags.add("disable:" + arg[len("--disable:"):].lower())
        elif arg.startswith("--force:"):
            flags.add("force:" + arg[len("--force:"):].lower())
        elif arg.startswith("--config:"):
            pair = arg[len("--config:"):]
            if "=" in pair:
                k, _, v = pair.partition("=")
                config[k.lower()] = v
        elif not arg.startswith("-"):
            urls.append(arg)
    return flags, config, urls

FLAGS, CONFIG, URL_ARGS = parse_args()

def flag(name):
    return name in FLAGS

def conf(name, default=""):
    return CONFIG.get(name.lower(), default)

def detect_system_dark():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except:
        return False

def make_white_icon(path, size):
    src = QPixmap(path).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    result = QPixmap(src.size())
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.drawPixmap(0, 0, src)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), QColor("white"))
    painter.end()
    return QIcon(result)

class TabProxy:
    def __init__(self):
        self.tabs = []
        self.routes = self.load_routes()
        self.search_template = self.load_search()

    def load_routes(self):
        routes = {}
        if os.path.exists(ROUTES_FILE):
            try:
                with open(ROUTES_FILE, "r", encoding="utf-8") as f:
                    for line in f.read().splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "(" in line and ")" in line:
                            key = line.split("(")[0].strip()
                            value = line.split("(")[1].split(")")[0].strip()
                            if value and not value.startswith("http"):
                                value = "https://" + value
                            routes[key] = value
            except Exception as e:
                print("Error loading routes:", e)
        return routes

    def load_search(self):
        default = "https://www.google.com/search?q={}"
        if os.path.exists(SEARCH_FILE):
            try:
                with open(SEARCH_FILE, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception as e:
                print("Error loading search:", e)
        return default

    BUBBLE_PAGES = {
        'bubble://gpu': 'chrome://gpu',
        'bubble://flags': 'chrome://flags',
        'bubble://version': 'chrome://version',
        'bubble://net': 'chrome://net-internals',
        'bubble://crashes': 'chrome://crashes',
    }
    BUBBLE_PAGES_REVERSE = {v: k for k, v in BUBBLE_PAGES.items()}

    def resolve_route(self, url):
        stripped = url.strip()
        if stripped in self.BUBBLE_PAGES:
            return self.BUBBLE_PAGES[stripped]
        return self.routes.get(stripped, url)

    def to_bubble_url(self, url):
        stripped = url.rstrip('/')
        for chrome_url, bubble_url in self.BUBBLE_PAGES_REVERSE.items():
            if stripped == chrome_url.rstrip('/') or url == chrome_url:
                return bubble_url
        return url

    def resolve_search(self, query):
        words = query.strip().split()
        if len(words) == 0:
            return self.search_template.format("")
        if "{word1}" in self.search_template and "{word2}" in self.search_template:
            separator = self.search_template.split("{word1}")[1].split("{word2}")[0]
            formatted = separator.join(quote_plus(word) for word in words)
            return self.search_template.split("{word1}")[0] + formatted + self.search_template.split("{word2}")[1]
        else:
            return self.search_template.format("+".join(quote_plus(word) for word in words))

    def register_tab(self, tab):
        self.tabs.append(tab)
        tab.proxy = self

    def unregister_tab(self, tab):
        if tab in self.tabs:
            self.tabs.remove(tab)

class BubbleTabBar(QTabBar):
    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setDrawBase(False)
        self.setMouseTracking(True)
        self._hover_close = -1
        self._x_color = "#dddddd" if theme == "dark" else "#666666"
        self._circle_color = QColor(255, 255, 255, 50) if theme == "dark" else QColor(0, 0, 0, 30)

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        size.setWidth(size.width() + 24)
        return size

    def _get_close_center(self, index):
        rect = self.tabRect(index)
        cx = rect.right() - 16
        cy = rect.center().y() + (2 if index != self.currentIndex() else 0)
        return cx, cy

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        prev = self._hover_close
        self._hover_close = -1
        for i in range(self.count()):
            cx, cy = self._get_close_center(i)
            dx = event.position().x() - cx
            dy = event.position().y() - cy
            if dx * dx + dy * dy <= 100:
                self._hover_close = i
                break
        if prev != self._hover_close:
            if prev >= 0:
                pcx, pcy = self._get_close_center(prev)
                self.update(pcx - 12, pcy - 12, 24, 24)
            if self._hover_close >= 0:
                ncx, ncy = self._get_close_center(self._hover_close)
                self.update(ncx - 12, ncy - 12, 24, 24)

    def mousePressEvent(self, event):
        for i in range(self.count()):
            cx, cy = self._get_close_center(i)
            dx = event.position().x() - cx
            dy = event.position().y() - cy
            if dx * dx + dy * dy <= 100:
                self.tabCloseRequested.emit(i)
                return
        super().mousePressEvent(event)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover_close = -1
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(self.count()):
            cx, cy = self._get_close_center(i)
            if self._hover_close == i:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._circle_color)
                painter.drawEllipse(cx - 10, cy - 10, 20, 20)
            pen = QPen(QColor(self._x_color))
            pen.setWidth(2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(cx - 3, cy - 3, cx + 3, cy + 3)
            painter.drawLine(cx + 3, cy - 3, cx - 3, cy + 3)
        painter.end()

class QuietWebPage(QWebEnginePage):
    def __init__(self, profile, parent):
        super().__init__(profile, parent)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        pass

class TabBubble(QObject):
    def __init__(self, title, url, parent_widget, profile, browser):
        super().__init__()
        self.title = title
        self.url = url
        self.proxy = None
        self.parent_widget = parent_widget
        self.browser = browser
        self.webview = QWebEngineView()
        self.webview.setMouseTracking(True)
        if flag("disable:interaction"):
            self.webview.setEnabled(False)
        page = QuietWebPage(profile, self.webview)
        self.webview.setPage(page)
        self.webview.titleChanged.connect(self.update_title)
        self.webview.urlChanged.connect(self.update_url)

    def load(self):
        self.webview.load(QUrl(self.url))

    def cleanup(self):
        try:
            self.webview.titleChanged.disconnect()
            self.webview.urlChanged.disconnect()
        except:
            pass
        self.webview.setParent(None)
        self.webview.deleteLater()

    def update_title(self, new_title):
        if new_title.strip():
            title = new_title
        else:
            raw_url = self.webview.url().toString()
            bubble = self.proxy.to_bubble_url(raw_url)
            if bubble != raw_url:
                title = bubble
            else:
                parsed = urlparse(raw_url)
                title = parsed.netloc or "New Tab"
        if len(title) > 20:
            title = title[:20] + "..."
        self.title = title
        index = self.parent_widget.indexOf(self.webview)
        if index >= 0:
            self.parent_widget.setTabText(index, self.title)

    def update_url(self, qurl):
        self.url = qurl.toString()
        display_url = self.proxy.to_bubble_url(self.url)
        if self.webview == self.parent_widget.currentWidget():
            if self.browser.address_bar:
                self.browser.address_bar.setText(display_url)

class BubbleEngine(QMainWindow):
    def __init__(self, profile):
        super().__init__()
        self.setWindowTitle("BubbleEngine")
        self.resize(1000, 700)
        self.profile = profile
        self.address_bar = None

        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PrintElementBackgrounds, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowWindowActivationFromJavaScript, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        backcol = conf("backcol", "light")
        if backcol == "system":
            self.effective_theme = "dark" if detect_system_dark() else "light"
        elif backcol == "dark":
            self.effective_theme = "dark"
        else:
            self.effective_theme = "light"

        spoof_script = """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        window.chrome = {
            runtime: {},
            loadTimes: function(){},
            csi: function(){},
            app: {}
        };
        Object.defineProperty(navigator, 'userAgentData', {
            get: () => ({
                brands: [
                    {brand: 'Google Chrome', version: '134'},
                    {brand: 'Chromium', version: '134'},
                    {brand: 'Not-A.Brand', version: '24'}
                ],
                mobile: false,
                platform: 'Windows',
                getHighEntropyValues: (hints) => Promise.resolve({
                    brands: [
                        {brand: 'Google Chrome', version: '134.0.6998.89'},
                        {brand: 'Chromium', version: '134.0.6998.89'},
                        {brand: 'Not-A.Brand', version: '24.0.0.0'}
                    ],
                    mobile: false,
                    platform: 'Windows',
                    platformVersion: '15.0.0',
                    architecture: 'x86',
                    bitness: '64',
                    uaFullVersion: '134.0.6998.89'
                })
            })
        });
        Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 0});
        Object.defineProperty(navigator, 'vendor', {get: () => 'Google Inc.'});
        Object.defineProperty(navigator, 'appVersion', {get: () => '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'});
        Object.defineProperty(navigator, 'appName', {get: () => 'Netscape'});
        const _omm = window.matchMedia.bind(window);
        window.matchMedia = function(q) {
            if (q === '(hover: none)') return Object.assign(Object.create(_omm(q)), {matches: false});
            if (q === '(hover: hover)') return Object.assign(Object.create(_omm(q)), {matches: true});
            if (q === '(pointer: coarse)') return Object.assign(Object.create(_omm(q)), {matches: false});
            if (q === '(pointer: fine)') return Object.assign(Object.create(_omm(q)), {matches: true});
            return _omm(q);
        };
        """

        spoof = QWebEngineScript()
        spoof.setName("spoof")
        spoof.setSourceCode(spoof_script)
        spoof.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        spoof.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self.profile.scripts().insert(spoof)

        hover_fix_script = """
(function() {
    var _lastX = -1, _lastY = -1, _lastEl = null;
    setInterval(function() {
        if (_lastX < 0) return;
        var cur = document.elementFromPoint(_lastX, _lastY);
        if (cur !== _lastEl) {
            if (document.body) {
                document.body.style.pointerEvents = 'none';
                void document.body.offsetHeight;
                document.body.style.pointerEvents = '';
            }
            _lastEl = cur;
        }
    }, 30);
    document.addEventListener('mousemove', function(e) {
        _lastX = e.clientX;
        _lastY = e.clientY;
    }, {passive: true, capture: true});
})();
"""
        hover_fix = QWebEngineScript()
        hover_fix.setName("hover_fix")
        hover_fix.setSourceCode(hover_fix_script)
        hover_fix.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        hover_fix.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self.profile.scripts().insert(hover_fix)

        forcefont = conf("forcefont", "none")
        if forcefont.lower() != "none":
            safe = forcefont.replace('"', '\\"')
            font_script = f"""
            (function() {{
                const s = document.createElement('style');
                s.id = 'bubble-font';
                s.textContent = '* {{ font-family: \\"{safe}\\" !important; }}';
                (document.head || document.documentElement).appendChild(s);
            }})();
            """
            inject = QWebEngineScript()
            inject.setName("bubble_inject")
            inject.setSourceCode(font_script)
            inject.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            inject.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            self.profile.scripts().insert(inject)

        self.proxy = TabProxy()
        self.tabs_widget = QTabWidget()
        self.tabs_widget.setTabBar(BubbleTabBar(self.effective_theme))
        self.tabs_widget.setTabsClosable(True)
        self.tabs_widget.tabBar().tabCloseRequested.connect(self.close_tab)
        self.tabs_widget.tabCloseRequested.connect(self.close_tab)
        self.tabs_widget.currentChanged.connect(self.tab_changed)
        for btn_pos in (QTabBar.ButtonPosition.RightSide, QTabBar.ButtonPosition.LeftSide):
            self.tabs_widget.tabBar().setTabButton(0, btn_pos, None)
        if flag("disable:topbar"):
            self.tabs_widget.tabBar().setVisible(False)

        is_dark = self.effective_theme == "dark"
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        if not flag("disable:topbar"):
            top_layout = QHBoxLayout()
            top_layout.setContentsMargins(4, 4, 4, 4)
            top_layout.setSpacing(4)

            if not flag("disable:navigationbutton"):
                self.back_btn = QPushButton()
                self.back_btn.setFixedSize(36, 36)
                self.back_btn.setIconSize(QSize(22, 22))
                self.back_btn.setToolTip("Back")
                back_path = os.path.join(ICONS_PATH, "back.png")
                if os.path.exists(back_path):
                    self.back_btn.setIcon(make_white_icon(back_path, 22) if is_dark else QIcon(back_path))
                else:
                    self.back_btn.setText("←")
                self.back_btn.clicked.connect(self.go_back)

                self.forward_btn = QPushButton()
                self.forward_btn.setFixedSize(36, 36)
                self.forward_btn.setIconSize(QSize(22, 22))
                self.forward_btn.setToolTip("Forward")
                fwd_path = os.path.join(ICONS_PATH, "forward.png")
                if os.path.exists(fwd_path):
                    self.forward_btn.setIcon(make_white_icon(fwd_path, 22) if is_dark else QIcon(fwd_path))
                else:
                    self.forward_btn.setText("→")
                self.forward_btn.clicked.connect(self.go_forward)

                self.refresh_btn = QPushButton()
                self.refresh_btn.setFixedSize(36, 36)
                self.refresh_btn.setIconSize(QSize(22, 22))
                self.refresh_btn.setToolTip("Refresh")
                ref_path = os.path.join(ICONS_PATH, "refresh.png")
                if os.path.exists(ref_path):
                    self.refresh_btn.setIcon(make_white_icon(ref_path, 22) if is_dark else QIcon(ref_path))
                else:
                    self.refresh_btn.setText("↻")
                self.refresh_btn.clicked.connect(self.refresh_tab)

                self.home_btn = QPushButton()
                self.home_btn.setFixedSize(28, 28)
                self.home_btn.setIconSize(QSize(16, 16))
                self.home_btn.setToolTip("Home")
                home_path = os.path.join(ICONS_PATH, "home.png")
                if os.path.exists(home_path):
                    self.home_btn.setIcon(make_white_icon(home_path, 16) if is_dark else QIcon(home_path))
                else:
                    self.home_btn.setText("⌂")
                self.home_btn.clicked.connect(self.go_home)

                self.add_tab_btn = QPushButton()
                self.add_tab_btn.setFixedSize(28, 28)
                self.add_tab_btn.setIconSize(QSize(16, 16))
                self.add_tab_btn.setToolTip("New Tab")
                newtab_path = os.path.join(ICONS_PATH, "newtab.png")
                if os.path.exists(newtab_path):
                    self.add_tab_btn.setIcon(make_white_icon(newtab_path, 16) if is_dark else QIcon(newtab_path))
                else:
                    self.add_tab_btn.setText("+")
                self.add_tab_btn.clicked.connect(self.open_new_tab)

                top_layout.addWidget(self.back_btn)
                top_layout.addWidget(self.forward_btn)
                top_layout.addWidget(self.refresh_btn)

            if not flag("disable:searchbar"):
                self.address_bar = QLineEdit()
                self.address_bar.setPlaceholderText("Enter URL or search...")
                self.address_bar.returnPressed.connect(self.navigate_from_bar)
                top_layout.addWidget(self.address_bar)

            if not flag("disable:navigationbutton"):
                top_layout.addWidget(self.home_btn)
                top_layout.addWidget(self.add_tab_btn)

            top_widget = QWidget()
            top_widget.setLayout(top_layout)
            main_layout.addWidget(top_widget)

        main_layout.addWidget(self.tabs_widget)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        if flag("disable:border"):
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)

        themes = {
            "dark": {
                "bg": "#1e1e1e", "fg": "#ffffff", "tab_bar_bg": "#1e1e1e",
                "tab_inactive": "#2a2a2a", "tab_active": "#3c3c3c", "tab_hover": "#333333",
                "input_bg": "#3a3a3a", "input_border": "#555555",
                "btn_bg": "#3a3a3a", "btn_hover": "#4a4a4a", "btn_pressed": "#555555",
            },
            "light": {
                "bg": "#f5f5f5", "fg": "#000000", "tab_bar_bg": "#f5f5f5",
                "tab_inactive": "#d8d8d8", "tab_active": "#ffffff", "tab_hover": "#c8c8c8",
                "input_bg": "#ffffff", "input_border": "#cccccc",
                "btn_bg": "#e0e0e0", "btn_hover": "#d0d0d0", "btn_pressed": "#c0c0c0",
            }
        }

        t = themes[self.effective_theme]
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {t['bg']}; }}
            QWidget {{ background-color: {t['bg']}; color: {t['fg']}; }}
            QLineEdit {{
                background-color: {t['input_bg']};
                color: {t['fg']};
                border: 1px solid {t['input_border']};
                border-radius: 4px;
                padding: 5px;
                font-size: 13px;
            }}
            QPushButton {{
                border: 1px solid {t['input_border']};
                border-radius: 4px;
                background-color: {t['btn_bg']};
                color: {t['fg']};
                padding: 4px;
            }}
            QPushButton:hover {{ background-color: {t['btn_hover']}; }}
            QPushButton:pressed {{ background-color: {t['btn_pressed']}; }}
            QTabWidget {{ background-color: {t['bg']}; border: none; }}
            QTabWidget::pane {{ border: none; background-color: {t['bg']}; margin: 0px; padding: 0px; top: -1px; }}
            QTabBar {{ background-color: {t['tab_bar_bg']}; border: none; }}
            QTabBar::tab {{
                background-color: {t['tab_inactive']};
                color: {t['fg']};
                padding: 7px 28px 7px 16px;
                margin-right: 3px;
                margin-top: 4px;
                min-width: 100px;
                border: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
            QTabBar::tab:selected {{
                background-color: {t['tab_active']};
                color: {t['fg']};
                font-weight: bold;
                margin-top: 1px;
            }}
            QTabBar::tab:hover:!selected {{ background-color: {t['tab_hover']}; }}
            QTabBar::close-button {{ width: 0px; height: 0px; border: none; background: transparent; }}
            QTabBar::close-button:hover {{ background: transparent; }}
        """)

        if forcefont.lower() != "none":
            self.setFont(QFont(forcefont))

    def get_start_page(self):
        url = "https://www.google.com"
        if os.path.exists(START_PAGE_FILE):
            try:
                with open(START_PAGE_FILE, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                    if raw:
                        resolved = self.proxy.resolve_route(raw)
                        if resolved != raw:
                            url = resolved
                        elif raw.startswith("http"):
                            url = raw
                        else:
                            url = "https://" + raw
            except Exception as e:
                print("Error reading start page:", e)
        return url

    def open_new_tab(self):
        self.open_tab(self.get_start_page())

    def navigate_from_bar(self):
        if not self.address_bar:
            return
        raw = self.address_bar.text().strip()
        if not raw:
            return
        url = self.proxy.resolve_route(raw)
        if url == raw:
            if not raw.startswith("http://") and not raw.startswith("https://"):
                if "." in raw and " " not in raw:
                    url = "https://" + raw
                else:
                    url = self.proxy.resolve_search(raw)
        current_widget = self.tabs_widget.currentWidget()
        if current_widget:
            current_widget.setUrl(QUrl(url))

    def open_tab(self, url):
        tab = TabBubble(title="Loading...", url=url, parent_widget=self.tabs_widget, profile=self.profile, browser=self)
        self.proxy.register_tab(tab)
        index = self.tabs_widget.addTab(tab.webview, tab.title)
        self.tabs_widget.setCurrentIndex(index)
        self.tabs_widget.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        self.tabs_widget.tabBar().setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)
        tab.load()

    def close_tab(self, index):
        if self.tabs_widget.count() <= 1:
            return
        widget = self.tabs_widget.widget(index)
        for tab in list(self.proxy.tabs):
            if tab.webview == widget:
                self.proxy.unregister_tab(tab)
                self.tabs_widget.removeTab(index)
                tab.cleanup()
                break

    def go_home(self):
        current = self.tabs_widget.currentWidget()
        if current:
            current.setUrl(QUrl(self.get_start_page()))

    def refresh_tab(self):
        current = self.tabs_widget.currentWidget()
        if current:
            current.reload()

    def go_back(self):
        current = self.tabs_widget.currentWidget()
        if current and current.history().canGoBack():
            current.back()

    def go_forward(self):
        current = self.tabs_widget.currentWidget()
        if current and current.history().canGoForward():
            current.forward()

    def tab_changed(self, index):
        if index >= 0 and self.address_bar:
            current_widget = self.tabs_widget.currentWidget()
            if current_widget:
                self.address_bar.setText(current_widget.url().toString())

if __name__ == "__main__":
    app = QApplication(sys.argv)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        "--disable-touch-drag-drop --disable-touch-editing "
        "--ignore-gpu-blocklist --enable-gpu-rasterization "
        "--enable-accelerated-video-decode "
        "--enable-gpu-compositing --enable-threaded-compositing "
        "--enable-accelerated-2d-canvas --enable-smooth-scrolling "
        "--disable-gpu-driver-bug-workarounds"
    )
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    QSurfaceFormat.setDefaultFormat(fmt)

    app.setOrganizationName("BubbleBrowse")
    app.setApplicationName("BubbleEngine")

    profile = QWebEngineProfile()
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    profile.setHttpUserAgent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    )

    browser = BubbleEngine(profile)

    if URL_ARGS:
        arg = URL_ARGS[0]
        if os.path.exists(arg):
            browser.open_tab(QUrl.fromLocalFile(os.path.abspath(arg)).toString())
        else:
            browser.open_tab(arg)
    else:
        browser.open_new_tab()

    if flag("force:fullscreen"):
        browser.showFullScreen()
    else:
        browser.show()

    sys.exit(app.exec())