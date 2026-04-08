import configparser
import os
from typing import Dict, Optional
from .utils import LumiUtils


class ConfigLoader:
    def __init__(self, config_dir: str = "config"):
        self._config_dir = config_dir
        self._build_settings = configparser.ConfigParser()
        self._devices = configparser.ConfigParser()
        self._device_configs: Dict[str, configparser.ConfigParser] = {}
        self._load_configs()

    def _load_configs(self) -> None:
        build_settings_path = os.path.join(self._config_dir, "build_settings.ini")
        devices_path = os.path.join(self._config_dir, "devices.ini")

        if LumiUtils.check_file(build_settings_path):
            self._build_settings.read(build_settings_path)

        if LumiUtils.check_file(devices_path):
            self._devices.read(devices_path)

    def _load_device_config(self, device: str) -> configparser.ConfigParser:
        if device in self._device_configs:
            return self._device_configs[device]

        device_ini = os.path.join(self._config_dir, "devices", f"{device}.ini")
        parser = configparser.ConfigParser()

        if LumiUtils.check_file(device_ini):
            parser.read(device_ini)

        self._device_configs[device] = parser
        return parser

    def get_build_setting(self, section: str, key: str, fallback=None):
        try:
            return self._build_settings.get(section, key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def get_build_setting_list(
        self, section: str, key: str, fallback=None, delimiter=","
    ):
        value = self.get_build_setting(section, key, fallback)
        if value is None:
            return fallback
        return [item.strip() for item in value.split(delimiter) if item.strip()]

    def get_build_setting_bool(
        self, section: str, key: str, fallback: bool = False
    ) -> bool:
        value = self.get_build_setting(section, key)
        if value is None:
            return fallback
        return str(value).upper() in ("TRUE", "YES", "1", "ON")

    def get_build_setting_int(self, section: str, key: str, fallback: int = 0) -> int:
        value = self.get_build_setting(section, key)
        if value is None:
            return fallback
        try:
            return int(str(value).strip())
        except ValueError:
            return fallback

    def get_device_base(self, device: str) -> str:
        return self._devices.get("devices", device, fallback="")

    def get_fw_url(self, base: str) -> str:
        return self._devices.get("fw_base", base, fallback="")

    def get_device_setting(self, device: str, key: str, fallback=None) -> Optional[str]:
        parser = self._load_device_config(device)
        try:
            return parser.get("device", key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def get_device_setting_int(self, device: str, key: str, fallback: int = 0) -> int:
        value = self.get_device_setting(device, key)
        if value is None:
            return fallback
        try:
            return int(value)
        except ValueError:
            return fallback

    def get_device_setting_bool(
        self, device: str, key: str, fallback: bool = False
    ) -> bool:
        value = self.get_device_setting(device, key)
        if value is None:
            return fallback
        return value.upper() in ("TRUE", "YES", "1", "ON")
