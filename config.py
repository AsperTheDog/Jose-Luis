import configparser
import random
from pathlib import Path
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