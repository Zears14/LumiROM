import os
import re
import shutil

from ..tools.debugfs import Debugfs
from ..tools.find import Find
from ..tools.unzip import Unzip
from ..tools.xxd import Xxd
from ..utils import LumiUtils
from .base_modifier import BaseModifier


class SystemExtFixerModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.debug("Entering SystemExtFixerModifier.apply")
        device = self.device
        has_separate = True
        if self._config_loader:
            separate = self._config_loader.get_device_setting(
                device, "stock_has_separate_system_ext", "TRUE"
            )
            has_separate = separate.upper() != "FALSE"

        system_ext_dir = os.path.join(self.firm_dir, "system_ext")
        if not LumiUtils.check_file(system_ext_dir):
            if self._resolve_system_ext_dir():
                self.logger.info(
                    "  system_ext already lives under system, skipping merge"
                )
            else:
                self.logger.info("  No system_ext partition found")
            return

        if has_separate:
            self.logger.info("  Device has separate system_ext, skipping merge")
            return

        self.logger.info("  Merging system_ext into system...")
        system_dir = os.path.join(self.firm_dir, "system")
        system_ext_config = os.path.join(
            self.firm_dir, "config", "system_ext_fs_config"
        )
        system_ext_contexts = os.path.join(
            self.firm_dir, "config", "system_ext_file_contexts"
        )
        system_config = os.path.join(self.firm_dir, "config", "system_fs_config")
        system_contexts = os.path.join(self.firm_dir, "config", "system_file_contexts")

        target_system_ext = os.path.join(system_dir, "system_ext")
        LumiUtils.remove_path(target_system_ext)
        LumiUtils.merge_tree(system_ext_dir, target_system_ext)

        if LumiUtils.check_file(system_ext_contexts):
            with open(system_ext_contexts, "r") as f:
                lines = f.readlines()
            lines = [
                line
                for line in lines
                if not re.match(
                    r"^/? (?:u:object_r:system_file:s0\s*$)"
                    r"|^/?system_ext(?:\(\.\*\)\?)?\s+u:object_r:system_file:s0\s*$"
                    r"|^/?system_ext/\s+u:object_r:system_file:s0\s*$",
                    line,
                )
            ]
            LumiUtils.replace_file_lines(system_ext_contexts, lines)

            with open(system_ext_contexts, "r") as f:
                content = f.read()
            LumiUtils.replace_file(
                system_ext_contexts,
                re.sub(r"^", "/system", content, flags=re.MULTILINE),
            )

            with open(system_contexts, "a") as f:
                with open(system_ext_contexts, "r") as src:
                    f.write(src.read())

        if LumiUtils.check_file(system_ext_config):
            with open(system_ext_config, "r") as f:
                lines = f.readlines()
            lines = [
                line
                for line in lines
                if not re.match(
                    r"^/?\s+0\s+0\s+0?755\s*$"
                    r"|^/?system_ext/?\s+0\s+0\s+0?755\s*$"
                    r"|^/?system_ext/lost\+found\s+0\s+0\s+0?755\s*$",
                    line,
                )
            ]
            LumiUtils.replace_file_lines(system_ext_config, lines)

            with open(system_ext_config, "r") as f:
                content = f.read()
            LumiUtils.replace_file(
                system_ext_config,
                re.sub(r"^", "system/", content, flags=re.MULTILINE),
            )

            with open(system_config, "a") as f:
                with open(system_ext_config, "r") as src:
                    f.write(src.read())

        LumiUtils.remove_path(system_ext_dir)
        for cfg in [system_ext_config, system_ext_contexts]:
            if LumiUtils.check_file(cfg):
                LumiUtils.remove_path(cfg)

        self.logger.info("  system_ext merged into system")

    def _resolve_system_ext_dir(self) -> str | None:
        candidates = [
            os.path.join(self.firm_dir, "system", "system_ext"),
            os.path.join(self.firm_dir, "system", "system", "system_ext"),
            os.path.join(self.firm_dir, "system_ext"),
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        return None


class DeodexModifier(BaseModifier):
    def apply(self) -> None:
        system_dir = os.path.join(self.firm_dir, "system")
        self.logger.info("  Deodexing ROM...")

        find_tool = Find(verbose=self._config.get("verbose", False))
        oat_dirs = find_tool.find_directories(system_dir, "oat")

        if oat_dirs:
            self.logger.info("    Found %d oat directories", len(oat_dirs))
            for oat_dir in oat_dirs:
                LumiUtils.remove_path(oat_dir)
            self.logger.info("    Deodex complete")


class BtLibPatcherModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Patching Bluetooth library...")
        apex_file = os.path.join(
            self.firm_dir, "system", "system", "apex", "com.android.bt.apex"
        )
        if not LumiUtils.check_file(apex_file):
            self.logger.info("  Bluetooth APEX not found, skipping BT patch")
            return

        os.makedirs(self.tmp_dir, exist_ok=True)
        bt_lib_so = os.path.join(self.tmp_dir, "libbluetooth_jni.so")
        apex_payload = os.path.join(self.tmp_dir, "apex_payload.img")

        unzip_tool = Unzip(self.tmp_dir, verbose=self._config.get("verbose", False))
        success = unzip_tool.extract(
            apex_file, ["apex_payload.img"], destination=self.tmp_dir
        )
        if not success or not LumiUtils.check_file(apex_payload):
            self.logger.warning("  Failed to extract apex payload")
            return

        debugfs_tool = Debugfs(verbose=self._config.get("verbose", False))
        success = debugfs_tool.dump(
            apex_payload, "/lib64/libbluetooth_jni.so", bt_lib_so
        )
        if not success or not LumiUtils.check_file(bt_lib_so):
            self.logger.warning("  Failed to extract Bluetooth library")
            return

        LumiUtils.remove_path(apex_payload)

        hex_patches = {
            136: ("00122a0140395f01086b00020054", "00122a0140395f01086bde030014"),
            135: ("480500352800805228", "530100142800805228"),
            234: ("4e7e4448bb", "4e7e4437e0"),
            233: ("4e7e4440bb", "4e7e4432e0"),
        }

        xxd_tool = Xxd(verbose=self._config.get("verbose", False))
        hexdata = xxd_tool.dump(bt_lib_so).lower()
        if not hexdata:
            self.logger.warning("  Failed to hex-dump Bluetooth library")
            return

        patched = False
        for offset, (from_hex, to_hex) in hex_patches.items():
            if from_hex.lower() in hexdata:
                self.logger.info("  Found BT patch pattern at offset %d", offset)
                if LumiUtils.hex_patch(bt_lib_so, from_hex, to_hex):
                    patched = True
                    break

        if patched:
            shutil.copy2(
                bt_lib_so,
                os.path.join(
                    self.firm_dir, "system", "system", "lib64", "libbluetooth_jni.so"
                ),
            )
            self.logger.info("  BT library patched and copied")
        else:
            self.logger.info("  No known BT patch pattern matched")

        LumiUtils.remove_path(bt_lib_so)
