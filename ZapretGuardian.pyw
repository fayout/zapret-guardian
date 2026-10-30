import os
import sys
import ctypes
import threading
import time
import socket
from tkinter import filedialog, messagebox

SINGLE_INSTANCE_PORT = 52199

def notify_existing_instance() -> bool:
    """Tries to connect to an existing instance and ask it to show itself."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.8)
            s.connect(("127.0.0.1", SINGLE_INSTANCE_PORT))
            s.sendall(b"RESTORE\n")
            return True
    except Exception:
        return False

# If an instance is already running, activate it and exit silently without any error or window
if notify_existing_instance():
    sys.exit(0)

# Ensure Admin elevation
def check_and_elevate():
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False

    if not is_admin:
        script = os.path.abspath(sys.argv[0])
        params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        python_exe = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(python_exe):
            python_exe = sys.executable

        ctypes.windll.shell32.ShellExecuteW(None, "runas", python_exe, f'"{script}" {params}', None, 1)
        sys.exit(0)

check_and_elevate()


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import customtkinter as ctk
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item, Menu

from config_manager import ConfigManager, auto_detect_zapret_dir
from strategy_parser import StrategyManager
from network_tester import NetworkTester
from hosts_manager import HostsManager

# Appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class SingleInstanceServer:
    """Listens on localhost socket to receive restore signals from duplicate launches."""
    def __init__(self, port=SINGLE_INSTANCE_PORT, on_restore_callback=None):
        self.port = port
        self.on_restore = on_restore_callback
        self.server_sock = None
        self.running = False
        self.thread = None

    def start(self):
        try:
            self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_sock.bind(("127.0.0.1", self.port))
            self.server_sock.listen(5)
            self.running = True
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            return True
        except Exception:
            return False

    def _listen_loop(self):
        while self.running:
            try:
                conn, _ = self.server_sock.accept()
                with conn:
                    conn.settimeout(1.0)
                    data = conn.recv(64)
                    if b"RESTORE" in data:
                        if self.on_restore:
                            self.on_restore()
            except Exception:
                if not self.running:
                    break

    def stop(self):
        self.running = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass


class ZapretGuardianApp:
    def __init__(self):
        self.config_mgr = ConfigManager()
        zapret_dir = self.config_mgr.get("zapret_dir")

        self.strategy_mgr = StrategyManager(zapret_dir)
        self.network_tester = NetworkTester(timeout=3.0)
        self.hosts_mgr = HostsManager(zapret_dir)

        # Single instance IPC listener
        self.single_instance = SingleInstanceServer(on_restore_callback=self.restore_from_tray)
        self.single_instance.start()

        self.root = ctk.CTk()
        self.root.title("Zapret Guardian 2.0 PRO — Панель управления")
        self.root.geometry("1040x740")
        self.root.minsize(920, 640)

        self.current_filter = "all"
        self.search_query = ""
        self.is_benchmarking = False
        self.tray_icon = None

        # Build UI
        self.create_widgets()

        # Build System Tray Icon
        self.setup_system_tray()

        # Intercept Close Window
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)

        # Initial data loading
        self.refresh_status()
        self.render_strategies()

        if self.config_mgr.get("auto_test_on_start", True):
            threading.Thread(target=self.run_network_test, daemon=True).start()

        # Periodic status refresh
        self.schedule_status_check()

    # =========================================================================
    # System Tray
    # =========================================================================
    def create_tray_image(self, is_active=True):
        color = "#10b981" if is_active else "#ef4444"
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        points = [(32, 4), (58, 14), (52, 44), (32, 60), (12, 44), (6, 14)]
        draw.polygon(points, fill=color)
        draw.line(points + [points[0]], fill="#ffffff", width=3)
        return img

    def setup_system_tray(self):
        menu = Menu(
            item("🛡️ Zapret Guardian 2.0", None, enabled=False),
            item(lambda text: f"Статус: {self.get_tray_status_text()}", None, enabled=False),
            Menu.SEPARATOR,
            item("⚡ Экспресс-Тест сети", lambda: threading.Thread(target=self.run_network_test, daemon=True).start()),
            item("Топ-Стратегии", Menu(
                item("🔥 general (ALT).bat", lambda: self.activate_strategy_async("general (ALT).bat")),
                item("general (ALT4).bat", lambda: self.activate_strategy_async("general (ALT4).bat")),
                item("general (ALT11).bat", lambda: self.activate_strategy_async("general (ALT11).bat")),
                item("general (FAKE TLS AUTO ALT).bat", lambda: self.activate_strategy_async("general (FAKE TLS AUTO ALT).bat")),
                item("general (ALT2).bat", lambda: self.activate_strategy_async("general (ALT2).bat")),
                item("general.bat", lambda: self.activate_strategy_async("general.bat")),
            )),
            item("⏹ Остановить WinWS", lambda: threading.Thread(target=self.stop_winws_worker, daemon=True).start()),
            Menu.SEPARATOR,
            item("🪟 Показать окно", self.restore_from_tray, default=True),
            item("❌ Выход", self.exit_application),
        )

        self.tray_icon = pystray.Icon(
            "ZapretGuardian",
            self.create_tray_image(True),
            "Zapret Guardian 2.0",
            menu
        )

        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def get_tray_status_text(self):
        proc = self.strategy_mgr.get_running_process()
        if proc:
            strat = self.strategy_mgr.detect_active_strategy(self.strategy_mgr.get_all_strategies()) or "Активен"
            return f"Работает ({strat})"
        return "Остановлен"

    def on_window_close(self):
        if self.config_mgr.get("minimize_to_tray", True):
            self.root.withdraw()
            try:
                if self.tray_icon:
                    self.tray_icon.notify("Приложение свернуто в трей. Кликните дважды, чтобы открыть.", "Zapret Guardian")
            except Exception:
                pass
        else:
            self.exit_application()

    def restore_from_tray(self):
        self.root.after(0, self._do_restore)

    def _do_restore(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
            self.root.update_idletasks()
            self.root.attributes("-topmost", False)
        except Exception:
            pass
        self.root.focus_force()

    def exit_application(self):
        if hasattr(self, "single_instance") and self.single_instance:
            self.single_instance.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # =========================================================================
    # GUI Layout & Tabs (Eliminates Scroll Lag!)
    # =========================================================================
    def create_widgets(self):
        # 1. Header Frame
        self.header_frame = ctk.CTkFrame(self.root, height=64, corner_radius=0, fg_color="#0e121c")
        self.header_frame.pack(fill="x", side="top")

        brand_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        brand_box.pack(side="left", padx=16, pady=10)

        ctk.CTkLabel(brand_box, text="🛡️", font=ctk.CTkFont(size=24)).pack(side="left", padx=(0, 8))

        t_box = ctk.CTkFrame(brand_box, fg_color="transparent")
        t_box.pack(side="left")

        ctk.CTkLabel(t_box, text="ZAPRET GUARDIAN 2.0", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(t_box, text="Панель управления WinWS", font=ctk.CTkFont(size=10), text_color="#64748b").pack(anchor="w")

        # Status Pill
        self.status_pill = ctk.CTkFrame(self.header_frame, fg_color="#07090e", corner_radius=18, border_width=1, border_color="#1c2436")
        self.status_pill.pack(side="left", padx=14, pady=12)

        self.lbl_status_dot = ctk.CTkLabel(self.status_pill, text="●", font=ctk.CTkFont(size=15), text_color="#10b981")
        self.lbl_status_dot.pack(side="left", padx=(12, 6))

        self.lbl_status_text = ctk.CTkLabel(self.status_pill, text="WINWS АКТИВЕН", font=ctk.CTkFont(size=11, weight="bold"))
        self.lbl_status_text.pack(side="left", padx=(0, 12))

        # Nav Actions
        actions = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        actions.pack(side="right", padx=16)

        btn_tray = ctk.CTkButton(actions, text="🔽 В трей", width=75, height=28, fg_color="#1e2638", hover_color="#334155", command=self.on_window_close)
        btn_tray.pack(side="right", padx=4)

        btn_stop = ctk.CTkButton(actions, text="⏹ Стоп", width=70, height=28, fg_color="#ef4444", hover_color="#b91c1c", command=lambda: threading.Thread(target=self.stop_winws_worker, daemon=True).start())
        btn_stop.pack(side="right", padx=4)

        btn_restart = ctk.CTkButton(actions, text="🔄 Рестарт", width=75, height=28, fg_color="#3b82f6", hover_color="#2563eb", command=self.restart_current_strategy)
        btn_restart.pack(side="right", padx=4)

        # 2. Main Tabview (Clean, zero tearing, ultra-smooth)
        self.tabview = ctk.CTkTabview(self.root, fg_color="#07090e", segmented_button_selected_color="#3b82f6", corner_radius=12)
        self.tabview.pack(fill="both", expand=True, padx=16, pady=(10, 16))

        self.tab_radar = self.tabview.add("🌐 Сетевой Радар")
        self.tab_strats = self.tabview.add("📦 Каталог Стратегий")
        self.tab_lists = self.tabview.add("📝 Списки Доменов")
        self.tab_settings = self.tabview.add("⚙️ Настройки & Пути")

        # Build each tab view
        self.build_radar_tab()
        self.build_strats_tab()
        self.build_lists_tab()
        self.build_settings_tab()

    # =========================================================================
    # Tab 1: Radar & Benchmark (No scrolling -> Zero lag!)
    # =========================================================================
    def build_radar_tab(self):
        f = self.tab_radar

        # Top Bar of Radar
        top_bar = ctk.CTkFrame(f, fg_color="#0e121c", corner_radius=10, border_width=1, border_color="#1c2436")
        top_bar.pack(fill="x", padx=10, pady=(10, 12))

        ctk.CTkLabel(top_bar, text="🌐 Мониторинг ключевых узлов Discord & YouTube", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=16, pady=12)

        self.btn_radar_test = ctk.CTkButton(
            top_bar,
            text="⚡ ПРОВЕРИТЬ СЕТЬ СЕЙЧАС",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=32,
            command=lambda: threading.Thread(target=self.run_network_test, daemon=True).start()
        )
        self.btn_radar_test.pack(side="right", padx=16, pady=10)

        # 4 Metric Cards Grid
        grid_frame = ctk.CTkFrame(f, fg_color="transparent")
        grid_frame.pack(fill="x", padx=6, pady=4)
        grid_frame.columnconfigure((0, 1, 2, 3), weight=1, uniform="col")

        self.card_dg = self.create_metric_card(grid_frame, 0, "💬", "Discord Gateway", "discord.com / API")
        self.card_dv = self.create_metric_card(grid_frame, 1, "🎙️", "Discord Voice (UDP)", "WebRTC / STUN")
        self.card_yw = self.create_metric_card(grid_frame, 2, "📺", "YouTube Web", "www.youtube.com")
        self.card_yc = self.create_metric_card(grid_frame, 3, "⚡", "YouTube 4K Stream", "googlevideo CDN")

        # Verdict Banner
        self.verdict_frame = ctk.CTkFrame(f, fg_color="#0e121c", corner_radius=10, border_width=1, border_color="#1c2436")
        self.verdict_frame.pack(fill="x", padx=10, pady=12)

        self.lbl_verdict = ctk.CTkLabel(
            self.verdict_frame,
            text="Инициализация... Нажмите «Проверить сеть сейчас» для замера отклика узлов.",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        )
        self.lbl_verdict.pack(padx=16, pady=12)

        # Auto-Optimizer Wizard Card
        wiz_box = ctk.CTkFrame(f, fg_color="#111827", corner_radius=12, border_width=1, border_color="#1f2937")
        wiz_box.pack(fill="x", padx=10, pady=(4, 10))

        inner = ctk.CTkFrame(wiz_box, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=14)

        ctk.CTkLabel(inner, text="🚀", font=ctk.CTkFont(size=28)).pack(side="left", padx=(0, 12))

        info = ctk.CTkFrame(inner, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(info, text="Умный Авто-Подбор Лучшей Стратегии (Auto-Benchmark)", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
        self.lbl_wiz_sub = ctk.CTkLabel(
            info,
            text="По очереди протестирует ключевые стратегии на вашем провайдере и включит победителя с наименьшим пингом.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        self.lbl_wiz_sub.pack(anchor="w", pady=(2, 0))

        self.btn_auto_bench = ctk.CTkButton(
            inner,
            text="⚡ Найти и Включить Лучшую",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#3b82f6",
            hover_color="#2563eb",
            height=34,
            command=lambda: threading.Thread(target=self.run_auto_benchmark, daemon=True).start()
        )
        self.btn_auto_bench.pack(side="right")

    def create_metric_card(self, parent, col, icon, title, sub):
        card = ctk.CTkFrame(parent, fg_color="#0e121c", corner_radius=10, border_width=1, border_color="#1c2436")
        card.grid(row=0, column=col, padx=4, pady=4, sticky="nsew")

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 2))

        ctk.CTkLabel(top, text=icon, font=ctk.CTkFont(size=18)).pack(side="left")
        badge = ctk.CTkLabel(top, text="ПРОВЕРКА", font=ctk.CTkFont(size=9, weight="bold"), text_color="#64748b")
        badge.pack(side="right")

        lbl_t = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1")
        lbl_t.pack(anchor="w", padx=10)

        lbl_val = ctk.CTkLabel(card, text="-- ms", font=ctk.CTkFont(size=20, weight="bold"))
        lbl_val.pack(anchor="w", padx=10, pady=(2, 2))

        lbl_s = ctk.CTkLabel(card, text=sub, font=ctk.CTkFont(size=9), text_color="#64748b")
        lbl_s.pack(anchor="w", padx=10, pady=(0, 8))

        return {"card": card, "badge": badge, "val": lbl_val}

    # =========================================================================
    # Tab 2: Strategies Catalog
    # =========================================================================
    def build_strats_tab(self):
        f = self.tab_strats

        # Search & Filter bar
        bar = ctk.CTkFrame(f, fg_color="#0e121c", corner_radius=10, border_width=1, border_color="#1c2436")
        bar.pack(fill="x", padx=10, pady=(10, 8))

        # Filter Chips
        chips_frame = ctk.CTkFrame(bar, fg_color="transparent")
        chips_frame.pack(side="left", padx=12, pady=10)

        filters = [
            ("all", "Все"),
            ("recommended", "🔥 Рекомендованные"),
            ("voice", "🎙️ С фиксом Voice"),
            ("fake", "⚡ Fake TLS"),
            ("split", "✂️ Multisplit")
        ]

        self.filter_buttons = {}
        for key, label in filters:
            btn = ctk.CTkButton(
                chips_frame,
                text=label,
                width=75,
                height=26,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#1e2638" if key != "all" else "#00f2fe",
                text_color="#fff" if key != "all" else "#000",
                hover_color="#334155",
                command=lambda k=key: self.set_filter(k)
            )
            btn.pack(side="left", padx=(0, 6))
            self.filter_buttons[key] = btn

        # Search Entry
        self.search_entry = ctk.CTkEntry(bar, placeholder_text="Поиск стратегии...", width=200, height=28)
        self.search_entry.pack(side="right", padx=12, pady=10)
        self.search_entry.bind("<KeyRelease>", self.on_search_change)

        # Dedicated scrollable list ONLY for strategy rows
        self.strat_list_frame = ctk.CTkScrollableFrame(f, fg_color="transparent", corner_radius=0)
        self.strat_list_frame.pack(fill="both", expand=True, padx=6, pady=(0, 10))

    # =========================================================================
    # Tab 3: Domain Lists
    # =========================================================================
    def build_lists_tab(self):
        f = self.tab_lists

        top_row = ctk.CTkFrame(f, fg_color="#0e121c", corner_radius=10, border_width=1, border_color="#1c2436")
        top_row.pack(fill="x", padx=10, pady=(10, 8))

        ctk.CTkLabel(top_row, text="📝 Редактор Доменов (list-general-user.txt)", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=16, pady=12)

        btn_save = ctk.CTkButton(top_row, text="💾 Сохранить список", width=130, height=28, fg_color="#10b981", hover_color="#059669", command=self.save_domains)
        btn_save.pack(side="right", padx=16)

        # Presets bar
        p_row = ctk.CTkFrame(f, fg_color="#0e121c", corner_radius=10, border_width=1, border_color="#1c2436")
        p_row.pack(fill="x", padx=10, pady=(0, 8))

        ctk.CTkLabel(p_row, text="Быстрые наборы:", font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(side="left", padx=(16, 10), pady=8)

        p_buttons = [
            ("discord", "🎙️ Discord Полный"),
            ("youtube", "📺 YouTube 4K & CDN"),
            ("trackers", "🧲 Торренты (RuTracker)"),
            ("ai_dev", "🧠 AI (ChatGPT, Claude)"),
        ]
        for key, name in p_buttons:
            btn = ctk.CTkButton(
                p_row,
                text=name,
                width=100,
                height=24,
                font=ctk.CTkFont(size=10),
                fg_color="#1e2638",
                hover_color="#334155",
                command=lambda k=key: self.apply_preset_domains(k)
            )
            btn.pack(side="left", padx=4, pady=8)

        # Textbox
        self.domain_textbox = ctk.CTkTextbox(f, font=ctk.CTkFont(family="Consolas", size=12), fg_color="#0e121c", border_width=1, border_color="#1c2436")
        self.domain_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Load initial content
        current_domains = self.hosts_mgr.read_domains("list-general-user")
        self.domain_textbox.insert("1.0", "\n".join(current_domains))

    # =========================================================================
    # Tab 4: Settings & Directory Path Picker
    # =========================================================================
    def build_settings_tab(self):
        f = self.tab_settings

        # 1. Directory Path Picker Box
        box_path = ctk.CTkFrame(f, fg_color="#0e121c", corner_radius=12, border_width=1, border_color="#1c2436")
        box_path.pack(fill="x", padx=10, pady=(10, 12))

        ctk.CTkLabel(box_path, text="📁 Расположение папки с Zapret", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=18, pady=(14, 4))
        ctk.CTkLabel(box_path, text="Укажите папку, где распакован zapret (в ней должна быть подпапка bin с winws.exe):", font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(anchor="w", padx=18, pady=(0, 10))

        row_picker = ctk.CTkFrame(box_path, fg_color="transparent")
        row_picker.pack(fill="x", padx=18, pady=(0, 8))

        self.entry_zapret_dir = ctk.CTkEntry(row_picker, font=ctk.CTkFont(family="Consolas", size=11), height=32)
        self.entry_zapret_dir.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.entry_zapret_dir.insert(0, self.strategy_mgr.zapret_dir)

        btn_browse = ctk.CTkButton(row_picker, text="📂 Обзор...", width=90, height=32, fg_color="#3b82f6", hover_color="#2563eb", command=self.browse_zapret_dir)
        btn_browse.pack(side="left", padx=4)

        btn_autofind = ctk.CTkButton(row_picker, text="🔍 Автопоиск", width=95, height=32, fg_color="#1e2638", hover_color="#334155", command=self.autofind_zapret_dir)
        btn_autofind.pack(side="left", padx=4)

        self.lbl_path_status = ctk.CTkLabel(box_path, text="", font=ctk.CTkFont(size=11, weight="bold"))
        self.lbl_path_status.pack(anchor="w", padx=18, pady=(0, 12))
        self.validate_and_show_path_status(self.strategy_mgr.zapret_dir)

        # 2. General Preferences Box
        box_pref = ctk.CTkFrame(f, fg_color="#0e121c", corner_radius=12, border_width=1, border_color="#1c2436")
        box_pref.pack(fill="x", padx=10, pady=(0, 12))

        ctk.CTkLabel(box_pref, text="⚙️ Поведение приложения", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=18, pady=(14, 8))

        self.chk_tray = ctk.CTkCheckBox(
            box_pref,
            text="Сворачивать в системный трей при закрытии окна (нажатии на крестик)",
            command=self.on_toggle_tray_pref
        )
        self.chk_tray.pack(anchor="w", padx=18, pady=6)
        if self.config_mgr.get("minimize_to_tray", True):
            self.chk_tray.select()

        self.chk_autotest = ctk.CTkCheckBox(
            box_pref,
            text="Автоматически проверять сеть (Discord & YouTube) при запуске программы",
            command=self.on_toggle_autotest_pref
        )
        self.chk_autotest.pack(anchor="w", padx=18, pady=(6, 16))
        if self.config_mgr.get("auto_test_on_start", True):
            self.chk_autotest.select()

        # 3. Actions row
        row_bot = ctk.CTkFrame(f, fg_color="transparent")
        row_bot.pack(fill="x", padx=10, pady=(0, 10))

        btn_open_folder = ctk.CTkButton(row_bot, text="📁 Открыть папку Zapret в Проводнике", fg_color="#1e2638", hover_color="#334155", command=self.open_zapret_folder)
        btn_open_folder.pack(side="left")

    def browse_zapret_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.strategy_mgr.zapret_dir, title="Выберите папку с Zapret")
        if chosen:
            self.set_new_zapret_dir(chosen)

    def autofind_zapret_dir(self):
        found = auto_detect_zapret_dir()
        if found:
            self.set_new_zapret_dir(found)
            messagebox.showinfo("Автопоиск", f"Zapret успешно найден по пути:\n{found}")
        else:
            messagebox.showwarning("Автопоиск", "Не удалось автоматически найти папку Zapret на дисках C: и D:.\nУкажите путь вручную через кнопку «Обзор...».")

    def set_new_zapret_dir(self, new_dir):
        if not self.config_mgr.is_valid_zapret_dir(new_dir):
            self.lbl_path_status.configure(text=f"❌ В папке «{new_dir}» не найден bin\\winws.exe!", text_color="#ef4444")
            return

        self.entry_zapret_dir.delete(0, "end")
        self.entry_zapret_dir.insert(0, new_dir)

        self.config_mgr.set("zapret_dir", new_dir)
        self.strategy_mgr.set_zapret_dir(new_dir)
        self.hosts_mgr.set_zapret_dir(new_dir)

        self.validate_and_show_path_status(new_dir)
        self.render_strategies()
        self.refresh_status()

    def validate_and_show_path_status(self, path):
        if self.config_mgr.is_valid_zapret_dir(path):
            self.lbl_path_status.configure(text=f"✅ Корректная папка Zapret (найден bin\\winws.exe, доступно стратегий: {len(self.strategy_mgr.get_all_strategies())})", text_color="#10b981")
        else:
            self.lbl_path_status.configure(text=f"❌ Ошибка: по пути «{path}» не найден bin\\winws.exe!", text_color="#ef4444")

    def on_toggle_tray_pref(self):
        self.config_mgr.set("minimize_to_tray", bool(self.chk_tray.get()))

    def on_toggle_autotest_pref(self):
        self.config_mgr.set("auto_test_on_start", bool(self.chk_autotest.get()))

    def open_zapret_folder(self):
        try:
            os.startfile(self.strategy_mgr.zapret_dir)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    # =========================================================================
    # Strategy Actions & Process Management (Direct elevated execution)
    # =========================================================================
    def set_filter(self, key):
        self.current_filter = key
        for k, btn in self.filter_buttons.items():
            if k == key:
                btn.configure(fg_color="#00f2fe", text_color="#000")
            else:
                btn.configure(fg_color="#1e2638", text_color="#fff")
        self.render_strategies()

    def on_search_change(self, event=None):
        self.search_query = self.search_entry.get().strip().lower()
        self.render_strategies()

    def render_strategies(self):
        for widget in self.strat_list_frame.winfo_children():
            widget.destroy()

        strategies = self.strategy_mgr.get_all_strategies()
        active_name = self.strategy_mgr.detect_active_strategy(strategies)

        filtered = []
        for s in strategies:
            fn = s["filename"].lower()
            if self.search_query and self.search_query not in fn and self.search_query not in s["description"].lower():
                continue

            if self.current_filter == "recommended" and not s["isRecommended"]:
                continue
            if self.current_filter == "voice" and not any("Discord Voice" in t for t in s["tags"]):
                continue
            if self.current_filter == "fake" and "fake" not in fn:
                continue
            if self.current_filter == "split" and "split" not in s["rawArgs"]:
                continue

            filtered.append(s)

        if not filtered:
            lbl_empty = ctk.CTkLabel(self.strat_list_frame, text="Стратегии по заданному фильтру не найдены", text_color="#64748b")
            lbl_empty.pack(pady=20)
            return

        for s in filtered:
            is_active = (s["filename"] == active_name)

            card = ctk.CTkFrame(
                self.strat_list_frame,
                fg_color="#0e121c" if not is_active else "#091a14",
                corner_radius=8,
                border_width=1,
                border_color="#10b981" if is_active else "#1c2436"
            )
            card.pack(fill="x", pady=3)

            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=7)

            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True)

            t_row = ctk.CTkFrame(left, fg_color="transparent")
            t_row.pack(anchor="w")

            ctk.CTkLabel(t_row, text=s["name"], font=ctk.CTkFont(size=13, weight="bold"), text_color="#fff" if not is_active else "#10b981").pack(side="left")

            if is_active:
                ctk.CTkLabel(t_row, text="АКТИВНА", font=ctk.CTkFont(size=9, weight="bold"), text_color="#10b981").pack(side="left", padx=8)

            ctk.CTkLabel(left, text=s["description"], font=ctk.CTkFont(size=10), text_color="#94a3b8").pack(anchor="w")

            btn_act = ctk.CTkButton(
                row,
                text="✓ Работает" if is_active else "⚡ Применить",
                width=105,
                height=26,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#10b981" if is_active else "#1e2638",
                hover_color="#059669" if is_active else "#3b82f6",
                command=lambda fn=s["filename"]: self.activate_strategy_async(fn)
            )
            btn_act.pack(side="right")

    def activate_strategy_async(self, filename):
        threading.Thread(target=self._activate_worker, args=(filename,), daemon=True).start()

    def _activate_worker(self, filename):
        res = self.strategy_mgr.start_strategy(filename)
        self.root.after(0, self.refresh_status)
        self.root.after(0, self.render_strategies)

        if res.get("success"):
            self.config_mgr.set("last_strategy", filename)
            try:
                if self.tray_icon:
                    self.tray_icon.notify(f"Стратегия {filename} запущена!", "Zapret Guardian")
            except Exception:
                pass
            time.sleep(1.8)
            self.run_network_test()
        else:
            self.root.after(0, lambda: messagebox.showerror("Ошибка запуска", res.get("error")))

    def stop_winws_worker(self):
        self.strategy_mgr.stop_winws()
        self.root.after(0, self.refresh_status)
        self.root.after(0, self.render_strategies)

    def restart_current_strategy(self):
        strategies = self.strategy_mgr.get_all_strategies()
        active = self.strategy_mgr.detect_active_strategy(strategies) or self.config_mgr.get("last_strategy", "general (ALT).bat")
        self.activate_strategy_async(active)

    def refresh_status(self):
        proc = self.strategy_mgr.get_running_process()
        strategies = self.strategy_mgr.get_all_strategies()
        active_strat = self.strategy_mgr.detect_active_strategy(strategies)

        if proc:
            self.lbl_status_dot.configure(text_color="#10b981")
            text = f"WINWS АКТИВЕН (PID: {proc['pid']})"
            if active_strat:
                text += f" | {active_strat}"
            self.lbl_status_text.configure(text=text)
            if self.tray_icon:
                self.tray_icon.icon = self.create_tray_image(True)
        else:
            self.lbl_status_dot.configure(text_color="#ef4444")
            self.lbl_status_text.configure(text="WINWS ОСТАНОВЛЕН")
            if self.tray_icon:
                self.tray_icon.icon = self.create_tray_image(False)

    def schedule_status_check(self):
        self.refresh_status()
        self.root.after(3000, self.schedule_status_check)

    # =========================================================================
    # Diagnostic Network Testing
    # =========================================================================
    def run_network_test(self):
        self.root.after(0, self._set_testing_visuals)
        report = self.network_tester.run_full_diagnostic()
        self.root.after(0, lambda: self._apply_test_results(report))

    def _set_testing_visuals(self):
        self.btn_radar_test.configure(state="disabled", text="⏳ ПРОВЕРКА...")
        for c in [self.card_dg, self.card_dv, self.card_yw, self.card_yc]:
            c["val"].configure(text="⏳")
            c["badge"].configure(text="ТЕСТ...", text_color="#00f2fe")
        self.lbl_verdict.configure(text="Идет опрос серверов Discord и YouTube...", text_color="#00f2fe")

    def _apply_test_results(self, report):
        self.btn_radar_test.configure(state="normal", text="⚡ ПРОВЕРИТЬ СЕТЬ СЕЙЧАС")

        dg = report["discord"]["api"]
        self.card_dg["val"].configure(text=f"{dg['latency']} ms")
        self.card_dg["badge"].configure(
            text="ДОСТУПЕН" if dg["status"] == "ok" else "БЛОК",
            text_color="#10b981" if dg["status"] == "ok" else "#ef4444"
        )

        dv = report["discord"]["voiceStun"]
        self.card_dv["val"].configure(text=f"{dv['latency']} ms" if dv["status"] == "ok" else "ТАЙМАУТ")
        self.card_dv["badge"].configure(
            text="ГОЛОС OK" if dv["status"] == "ok" else "RTC ОШИБКА",
            text_color="#10b981" if dv["status"] == "ok" else "#ef4444"
        )

        yw = report["youtube"]["web"]
        self.card_yw["val"].configure(text=f"{yw['latency']} ms")
        self.card_yw["badge"].configure(
            text="ДОСТУПЕН" if yw["status"] == "ok" else "БЛОК",
            text_color="#10b981" if yw["status"] == "ok" else "#ef4444"
        )

        yc = report["youtube"]["cdn"]
        self.card_yc["val"].configure(text=f"{yc['latency']} ms")
        self.card_yc["badge"].configure(
            text="4K STREAM OK" if yc["status"] == "ok" else "БУФЕР",
            text_color="#10b981" if yc["status"] == "ok" else "#ef4444"
        )

        v_color = "#10b981" if report["verdict"] == "perfect" else ("#f59e0b" if "only" in report["verdict"] or report["verdict"] == "good" else "#ef4444")
        self.lbl_verdict.configure(
            text=f"Индекс проходимости: {report['overallScore']}% — {report['verdictText']}",
            text_color=v_color
        )

    # =========================================================================
    # Auto-Benchmark Wizard
    # =========================================================================
    def run_auto_benchmark(self):
        if self.is_benchmarking:
            return
        self.is_benchmarking = True
        self.btn_auto_bench.configure(state="disabled", text="⏳ Подбор...")

        candidates = [
            "general (ALT).bat",
            "general (ALT4).bat",
            "general (ALT11).bat",
            "general (FAKE TLS AUTO ALT).bat",
            "general (ALT2).bat",
            "general.bat",
        ]

        available = [s["filename"] for s in self.strategy_mgr.get_all_strategies()]
        to_test = [c for c in candidates if c in available]

        results = []
        for strat in to_test:
            self.lbl_wiz_sub.configure(text=f"Тестирование: {strat} ...")
            self.strategy_mgr.start_strategy(strat)
            time.sleep(2.0)

            diag = self.network_tester.run_full_diagnostic()
            voice_ok = diag["discord"]["voiceStun"]["status"] == "ok"
            voice_latency = diag["discord"]["voiceStun"]["latency"]
            results.append({
                "strat": strat,
                "score": diag["overallScore"],
                "voice_ok": voice_ok,
                "voice_latency": voice_latency,
                "yt_latency": diag["youtube"]["averageLatency"]
            })

        results.sort(key=lambda r: (1 if r["voice_ok"] else 0, r["score"], -r["voice_latency"]), reverse=True)
        winner = results[0] if results else None

        if winner:
            self.strategy_mgr.start_strategy(winner["strat"])
            self.lbl_wiz_sub.configure(text=f"✅ Победитель: {winner['strat']} (Голос: {winner['voice_latency']} ms | YouTube: {winner['yt_latency']} ms)")
        else:
            self.lbl_wiz_sub.configure(text="Тестирование завершено.")

        self.is_benchmarking = False
        self.btn_auto_bench.configure(state="normal", text="⚡ Найти и Включить Лучшую")
        self.refresh_status()
        self.render_strategies()
        self.run_network_test()

    # =========================================================================
    # Domain Lists Actions
    # =========================================================================
    def save_domains(self):
        raw = self.domain_textbox.get("1.0", "end-1c")
        domains = [d.strip() for d in raw.split("\n") if d.strip()]
        ok = self.hosts_mgr.write_domains(domains, "list-general-user")
        if ok:
            messagebox.showinfo("Списки", "Список доменов успешно сохранен в list-general-user.txt!")

    def apply_preset_domains(self, preset_key):
        updated = self.hosts_mgr.apply_preset(preset_key, "list-general-user")
        self.domain_textbox.delete("1.0", "end")
        self.domain_textbox.insert("1.0", "\n".join(updated))
        messagebox.showinfo("Набор добавлен", f"Домены набора «{preset_key}» успешно добавлены в список!")


if __name__ == "__main__":
    app = ZapretGuardianApp()
    app.root.mainloop()
