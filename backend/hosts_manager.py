import os
from typing import List, Dict, Any

try:
    from config_manager import auto_detect_zapret_dir
    DEFAULT_ZAPRET_DIR = auto_detect_zapret_dir() or r"C:\zapret-discord-youtube-1.10.4"
except ImportError:
    try:
        from backend.config_manager import auto_detect_zapret_dir
        DEFAULT_ZAPRET_DIR = auto_detect_zapret_dir() or r"C:\zapret-discord-youtube-1.10.4"
    except ImportError:
        DEFAULT_ZAPRET_DIR = r"C:\zapret-discord-youtube-1.10.4"


PRESETS = {
    "discord": {
        "name": "Discord & Voice",
        "description": "Полный стек Discord (API, Web, Voice, CDN, Gateway)",
        "domains": [
            "discord.com",
            "discordapp.com",
            "discord.gg",
            "discord.media",
            "gateway.discord.gg",
            "cdn.discordapp.com",
            "updates.discord.com",
            "status.discord.com",
        ],
    },
    "youtube": {
        "name": "YouTube 4K & CDN",
        "description": "YouTube, Googlevideo CDN, превью и шортсы",
        "domains": [
            "youtube.com",
            "youtu.be",
            "googlevideo.com",
            "ytimg.com",
            "i.ytimg.com",
            "ggpht.com",
            "youtubei.googleapis.com",
        ],
    },
    "trackers": {
        "name": "Торрент-трекеры",
        "description": "RuTracker, Rutor, NNM-Club",
        "domains": [
            "rutracker.org",
            "rutracker.net",
            "rutor.info",
            "rutor.is",
            "nnmclub.to",
        ],
    },
    "ai_dev": {
        "name": "AI & Разработка",
        "description": "ChatGPT, Claude, Notion, OpenAI",
        "domains": [
            "chatgpt.com",
            "openai.com",
            "claude.ai",
            "anthropic.com",
            "notion.so",
        ],
    },
}

class HostsManager:
    def __init__(self, zapret_dir: str = DEFAULT_ZAPRET_DIR):
        self.set_zapret_dir(zapret_dir)

    def set_zapret_dir(self, new_dir: str):
        self.zapret_dir = new_dir
        self.lists_dir = os.path.join(new_dir, "lists")

    def get_list_path(self, list_name: str) -> str:
        filename = f"{list_name}.txt"
        return os.path.join(self.lists_dir, filename)

    def read_domains(self, list_name: str = "list-general-user") -> List[str]:
        path = self.get_list_path(list_name)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
                return sorted(list(set(lines)))
        except Exception:
            return []

    def write_domains(self, domains: List[str], list_name: str = "list-general-user") -> bool:
        path = self.get_list_path(list_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cleaned = sorted(list(set([d.strip().lower() for d in domains if d.strip()])))
        try:
            with open(path, "w", encoding="utf-8") as f:
                for d in cleaned:
                    f.write(f"{d}\n")
            return True
        except Exception as e:
            print(f"Error writing {list_name}: {e}")
            return False

    def add_domains(self, new_domains: List[str], list_name: str = "list-general-user") -> List[str]:
        current = set(self.read_domains(list_name))
        for d in new_domains:
            clean = d.strip().lower()
            if clean:
                current.add(clean)
        updated = sorted(list(current))
        self.write_domains(updated, list_name)
        return updated

    def remove_domain(self, domain: str, list_name: str = "list-general-user") -> List[str]:
        current = set(self.read_domains(list_name))
        current.discard(domain.strip().lower())
        updated = sorted(list(current))
        self.write_domains(updated, list_name)
        return updated

    def apply_preset(self, preset_key: str, list_name: str = "list-general-user") -> List[str]:
        if preset_key in PRESETS:
            return self.add_domains(PRESETS[preset_key]["domains"], list_name)
        return self.read_domains(list_name)

    def get_presets_info(self) -> Dict[str, Any]:
        return PRESETS
