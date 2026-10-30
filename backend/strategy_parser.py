import os
import re
import subprocess
import psutil
from typing import List, Dict, Any, Optional

try:
    from config_manager import auto_detect_zapret_dir
    DEFAULT_ZAPRET_DIR = auto_detect_zapret_dir() or r"C:\zapret-discord-youtube-1.10.4"
except ImportError:
    try:
        from backend.config_manager import auto_detect_zapret_dir
        DEFAULT_ZAPRET_DIR = auto_detect_zapret_dir() or r"C:\zapret-discord-youtube-1.10.4"
    except ImportError:
        DEFAULT_ZAPRET_DIR = r"C:\zapret-discord-youtube-1.10.4"


class StrategyManager:
    def __init__(self, zapret_dir: str = DEFAULT_ZAPRET_DIR):
        self.set_zapret_dir(zapret_dir)
        self.active_process = None
        self.current_strategy_name = None

    def set_zapret_dir(self, new_dir: str):
        self.zapret_dir = new_dir
        self.bin_dir = os.path.join(new_dir, "bin")
        self.lists_dir = os.path.join(new_dir, "lists")
        self.winws_path = os.path.join(self.bin_dir, "winws.exe")

    def get_all_strategies(self) -> List[Dict[str, Any]]:
        """Scans the zapret directory for all general*.bat strategy files and parses their arguments."""
        if not os.path.exists(self.zapret_dir):
            return []

        strategies = []
        files = [f for f in os.listdir(self.zapret_dir) if f.startswith("general") and f.endswith(".bat")]

        def sort_key(name):
            if name == "general.bat":
                return (0, 0, name)
            if "ALT" in name:
                num = re.search(r"ALT(\d+)", name)
                val = int(num.group(1)) if num else 1
                return (1, val, name)
            if "FAKE TLS" in name:
                return (2, 0, name)
            return (3, 0, name)

        files.sort(key=sort_key)

        for filename in files:
            filepath = os.path.join(self.zapret_dir, filename)
            try:
                with open(filepath, "r", encoding="cp1251", errors="ignore") as f:
                    content = f.read()

                m = re.search(r'\"%BIN%winws\.exe\"\s+(.*)', content, re.DOTALL)
                raw_args = ""
                if m:
                    raw_args = m.group(1).replace("^\n", " ").replace("^\r\n", " ").replace("^", " ").strip()
                    raw_args = raw_args.replace("%BIN%", self.bin_dir + "\\")
                    raw_args = raw_args.replace("%LISTS%", self.lists_dir + "\\")
                    raw_args = re.sub(r"%GameFilterTCP%", "12", raw_args)
                    raw_args = re.sub(r"%GameFilterUDP%", "12", raw_args)
                    raw_args = " ".join(raw_args.split())

                tags = []
                desc = "Стандартная стратегия обхода блокировок"
                is_recommended = False

                if filename in ["general (ALT).bat", "general (ALT4).bat", "general (ALT11).bat", "general (FAKE TLS AUTO ALT).bat"]:
                    is_recommended = True
                    tags.append("🔥 ТОП")

                if "fake-discord" in raw_args or "ACTIVE_DISCORD_UDP" in raw_args:
                    tags.append("🎙️ Discord Voice Fix")
                if "fakedsplit" in raw_args:
                    tags.append("Faked Split")
                elif "multisplit" in raw_args:
                    tags.append("Multi Split")

                if "FAKE TLS AUTO" in filename.upper():
                    tags.append("Auto Fake TLS")
                    desc = "Автоматический подбор фейкового TLS с расширенным спуфингом"
                elif "sferum" in raw_args:
                    tags.append("Sferum SNI")
                    desc = "Маскировка под образовательный трафик (Сферум)"
                elif "google" in raw_args:
                    tags.append("Google SNI")
                    desc = "Спуфинг Google TLS / QUIC"

                if "quic" in raw_args:
                    tags.append("QUIC/HTTP3")

                strategies.append({
                    "id": filename,
                    "filename": filename,
                    "name": filename.replace(".bat", ""),
                    "description": desc,
                    "tags": tags,
                    "isRecommended": is_recommended,
                    "rawArgs": raw_args,
                    "filePath": filepath,
                })
            except Exception as e:
                print(f"Error parsing {filename}: {e}")

        return strategies

    def get_running_process(self) -> Optional[Dict[str, Any]]:
        """Checks if winws.exe is currently running, and returns PID and cmdline."""
        for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            try:
                name = (p.info["name"] or "").lower()
                if name == "winws.exe":
                    cmdline = p.info.get("cmdline") or []
                    joined_cmd = " ".join(cmdline)
                    return {
                        "pid": p.info["pid"],
                        "cmdline": cmdline,
                        "rawCmd": joined_cmd,
                        "uptime": int(psutil.time.time() - p.info["create_time"]),
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def detect_active_strategy(self, strategies: List[Dict[str, Any]]) -> Optional[str]:
        """Matches running winws process args with known strategy files."""
        if self.current_strategy_name:
            # If we started it ourselves and it's still alive, return it
            if self.get_running_process():
                return self.current_strategy_name

        running = self.get_running_process()
        if not running:
            return None

        running_cmd = running["rawCmd"].lower()
        best_match = None
        highest_score = 0

        for s in strategies:
            filename = s["filename"].lower()
            if filename in running_cmd:
                return s["filename"]

            s_tokens = set(s["rawArgs"].lower().split())
            if not s_tokens:
                continue

            run_tokens = set(running_cmd.split())
            overlap = len(s_tokens.intersection(run_tokens))
            ratio = overlap / len(s_tokens)

            if ratio > 0.75 and overlap > highest_score:
                highest_score = overlap
                best_match = s["filename"]

        return best_match

    def stop_winws(self) -> bool:
        """Kills any running winws.exe processes and resets WinDivert."""
        stopped = False
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if (p.info["name"] or "").lower() == "winws.exe":
                    p.kill()
                    stopped = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        try:
            subprocess.run(["sc.exe", "stop", "zapret"], capture_output=True, timeout=3)
        except Exception:
            pass

        self.current_strategy_name = None
        self.active_process = None
        psutil.time.sleep(0.4)
        return stopped

    def start_strategy(self, filename: str) -> Dict[str, Any]:
        """
        Directly launches winws.exe with the exact arguments from the chosen strategy!
        Uses CREATE_NO_WINDOW so it runs silently in the background with zero terminal popups.
        """
        strategies = {s["filename"]: s for s in self.get_all_strategies()}
        if filename not in strategies:
            return {"success": False, "error": f"Стратегия {filename} не найдена"}

        strategy = strategies[filename]
        raw_args = strategy["rawArgs"]

        # 1. Stop existing winws
        self.stop_winws()

        if not os.path.exists(self.winws_path):
            return {"success": False, "error": f"winws.exe не найден по пути: {self.winws_path}"}

        try:
            # Build full executable command
            # Split args properly or pass as full command line string on Windows
            full_cmd = f'"{self.winws_path}" {raw_args}'

            # Launch with CREATE_NO_WINDOW (0x08000000)
            self.active_process = subprocess.Popen(
                full_cmd,
                cwd=self.bin_dir,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            self.current_strategy_name = filename

            # Verify it didn't immediately crash (e.g. WinDivert error)
            for _ in range(15):
                psutil.time.sleep(0.2)
                proc = self.get_running_process()
                if proc:
                    return {"success": True, "strategy": filename, "pid": proc["pid"]}

            return {"success": False, "error": "winws.exe запустился, но завершился с ошибкой (проверьте права администратора)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_service_status(self) -> Dict[str, Any]:
        """Checks Windows Service 'zapret' state."""
        try:
            res = subprocess.run(["sc.exe", "query", "zapret"], capture_output=True, text=True, timeout=3)
            out = res.stdout.upper()
            if "RUNNING" in out:
                return {"installed": True, "state": "RUNNING"}
            elif "STOPPED" in out:
                return {"installed": True, "state": "STOPPED"}
            elif "1060" in out or "DOES NOT EXIST" in out or "НЕ СУЩЕСТВУЕТ" in out:
                return {"installed": False, "state": "NOT_INSTALLED"}
            else:
                return {"installed": True, "state": "UNKNOWN"}
        except Exception as e:
            return {"installed": False, "error": str(e)}

    def install_service(self, filename: str) -> Dict[str, Any]:
        """Installs the chosen strategy as an auto-start Windows Service."""
        strategies = {s["filename"]: s for s in self.get_all_strategies()}
        if filename not in strategies:
            return {"success": False, "error": "Стратегия не найдена"}

        strategy = strategies[filename]
        raw_args = strategy["rawArgs"]

        self.stop_winws()

        try:
            subprocess.run(["sc.exe", "delete", "zapret"], capture_output=True, timeout=3)
            psutil.time.sleep(0.5)

            bin_path = f'\\"{self.winws_path}\\" {raw_args}'
            cmd_create = [
                "sc.exe",
                "create",
                "zapret",
                f"binPath= {bin_path}",
                "DisplayName= zapret",
                "start= auto",
            ]
            res1 = subprocess.run(cmd_create, capture_output=True, text=True, timeout=5)
            if res1.returncode != 0:
                return {"success": False, "error": f"sc create failed: {res1.stdout} {res1.stderr}"}

            subprocess.run(
                ["sc.exe", "description", "zapret", "Zapret DPI bypass service managed by Zapret Guardian"],
                capture_output=True,
                timeout=3,
            )

            res2 = subprocess.run(["sc.exe", "start", "zapret"], capture_output=True, text=True, timeout=5)
            return {"success": True, "service": "zapret", "strategy": filename}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def uninstall_service(self) -> Dict[str, Any]:
        """Stops and deletes the zapret Windows Service."""
        try:
            subprocess.run(["sc.exe", "stop", "zapret"], capture_output=True, timeout=4)
            subprocess.run(["sc.exe", "delete", "zapret"], capture_output=True, timeout=4)
            self.stop_winws()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
