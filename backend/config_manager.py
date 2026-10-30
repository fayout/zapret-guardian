import os
import json
from typing import Dict, Any, Optional

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(APP_DIR, "settings.json")

COMMON_ZAPRET_PATHS = [
    r"C:\zapret-discord-youtube-1.10.4",
    r"C:\zapret-discord-youtube-1.10.3",
    r"C:\zapret-discord-youtube-1.10.2",
    r"C:\zapret-discord-youtube",
    r"C:\zapret",
    r"D:\zapret-discord-youtube-1.10.4",
    r"D:\zapret-discord-youtube",
    r"D:\zapret",
]

def auto_detect_zapret_dir() -> Optional[str]:
    """Finds the first existing zapret installation with bin/winws.exe."""
    for path in COMMON_ZAPRET_PATHS:
        if os.path.exists(os.path.join(path, "bin", "winws.exe")):
            return path
    return None

class ConfigManager:
    def __init__(self, filepath: str = CONFIG_FILE):
        self.filepath = filepath
        self.config = self.load()

    def load(self) -> Dict[str, Any]:
        default_dir = auto_detect_zapret_dir() or r"C:\zapret-discord-youtube-1.10.4"
        defaults = {
            "zapret_dir": default_dir,
            "minimize_to_tray": True,
            "auto_test_on_start": True,
            "last_strategy": "general (ALT).bat",
        }
        if not os.path.exists(self.filepath):
            self.save(defaults)
            return defaults

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in defaults.items():
                    if k not in data:
                        data[k] = v
                return data
        except Exception:
            return defaults

    def save(self, data: Optional[Dict[str, Any]] = None):
        if data:
            self.config = data
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        self.config[key] = value
        self.save()

    def is_valid_zapret_dir(self, directory: str) -> bool:
        if not directory or not os.path.isdir(directory):
            return False
        winws_path = os.path.join(directory, "bin", "winws.exe")
        return os.path.exists(winws_path)
