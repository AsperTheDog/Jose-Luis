import configparser
import random
from typing import Any, Dict, Optional


class ConfigManager:
    DEFAULT_CONFIG: Dict[str, Any] = {
        "admin_channel_id": 0,
        "log_channel_id": 0,
        "death_channel_id": 0,
        "death_grace_seconds": 60.0,
        "global_cooldown_seconds": 600.0,
        "burst_message_count": 10,
        "burst_time_window": 60.0,
        "operators": "[]",
        "channel_whitelist": "[]"
    }

    def __init__(self, config_path: str = "config.cfg"):
        self.path = Path(config_path)
        self.parser = configparser.ConfigParser()

        if self.path.exists():
            self.load()
        else:
            self._create_default_config()

    def load(self) -> None:
        self.parser.read(self.path, encoding="utf-8")

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            self.parser.write(f)

    def _create_default_config(self) -> None:
        self.parser.add_section("BOT")
        for option, value in self.DEFAULT_CONFIG.items():
            self.parser['BOT'][option] = str(value)
        self.save()
        print(f"Created default configuration file at: {self.path.resolve()}")

    def get(self, option: str, fallback: Any = None) -> Any:
        elem = self.parser.get("BOT", option, fallback=fallback)
        if elem is None:
            return None
        return elem

    def get_int(self, option: str, fallback: int = 0) -> int:
        return self.parser.getint("BOT", option, fallback=fallback)

    def get_float(self, option: str, fallback: int = 0) -> float:
        return self.parser.getfloat("BOT", option, fallback=fallback)

    def get_boolean(self, option: str, fallback: bool = False) -> bool:
        return self.parser.getboolean("BOT", option, fallback=fallback)

    def set(self, option: str, value: Any, auto_save: bool = True) -> None:
        self.parser.set("BOT", option, str(value))
        if auto_save:
            self.save()

    def get_list(self, option: str, fallback: List[str] | None = None) -> List[str]:
        raw_val = self.get(option, fallback="")
        if not raw_val or not raw_val.strip():
            return fallback if fallback is not None else []
        return [item.strip() for item in raw_val.replace('[', '').replace(']', '').split(",") if item.strip() != ""]

    def add_to_list(self, option: str, item: Any, auto_save: bool = True) -> bool:
        item_str = str(item).strip()
        current_list = self.get_list(option)

        if item_str not in current_list:
            current_list.append(item_str)
            self.set(option, ",".join(current_list), auto_save=auto_save)
            return True
        return False

    def remove_from_list(self, option: str, item: Any, auto_save: bool = True) -> bool:
        item_str = str(item).strip()
        current_list = self.get_list(option)

        if item_str in current_list:
            current_list.remove(item_str)
            self.set(option, ",".join(current_list), auto_save=auto_save)
            return True
        return False

from pathlib import Path
from typing import List, Set


class ListConfig:
    def __init__(self, config_path: str, separator: str = "||") -> None:
        self.path = Path(config_path)
        self.separator = separator
        self._cache: Set[str] = self._load_from_disk()
        self._recent_history: List[str] = []
        self._load_from_disk()

    def _load_from_disk(self) -> Set[str]:
        if not self.path.exists():
            return set()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                content = f.read()
            return {
                elem.strip()
                for elem in content.split(self.separator)
                if elem.strip()
            }
        except OSError:
            return set()

    def _flush_to_disk(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            if self._cache:
                f.write(self.separator.join(self._cache) + self.separator)

    def get_all(self) -> List[str]:
        return list(self._cache)

    def contains(self, element: str) -> bool:
        return element.strip() in self._cache

    def add(self, element: str) -> bool:
        elem_str = element.strip()
        if not elem_str or elem_str in self._cache:
            return False

        self._cache.add(elem_str)
        self._flush_to_disk()
        return True

    def remove(self, element: str) -> bool:
        elem_str = element.strip()
        if elem_str not in self._cache:
            return False

        self._cache.remove(elem_str)
        self._flush_to_disk()
        return True

    def set(self, elems: List[str]) -> None:
        new_cache = {e.strip() for e in elems if e.strip()}
        if new_cache == self._cache:
            return

        self._cache = new_cache
        self._flush_to_disk()

    def pick_random(self, history_ratio: float = 0.4) -> Optional[str]:
        if not self._cache:
            return "FALLO: No hay nada aquí entre lo que elegir..."

        candidates = list(self._cache)
        if len(candidates) == 1:
            return candidates[0]

        max_history_len = max(1, min(len(candidates) - 1, int(len(candidates) * history_ratio)))
        available = [item for item in candidates if item not in self._recent_history]

        if not available:
            self._recent_history.clear()
            available = candidates

        chosen = random.choice(available)

        self._recent_history.append(chosen)
        if len(self._recent_history) > max_history_len:
            self._recent_history.pop(0)  # Evict oldest choice

        return chosen