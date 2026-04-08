import configparser
import os
import re
import shutil
from typing import Dict

from ..utils import LumiUtils
from .base_modifier import BaseModifier


class StockConfigApplierModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Applying stock config...")
        device = self.device
        devices_dir = os.path.join(self.ws_root, "LumiROM", "Devices")

        stock_vndk_version = "31"
        if self._config_loader:
            vndk = self._config_loader.get_device_setting(
                device, "stock_vndk_version", "31"
            )
            if vndk:
                stock_vndk_version = vndk

        self._config["_stock_vndk_version"] = stock_vndk_version

        floating_feature_src = os.path.join(devices_dir, device, "floating_feature.xml")
        floating_feature_dst = os.path.join(
            self.firm_dir, "system", "system", "etc", "floating_feature.xml"
        )

        if LumiUtils.check_file(floating_feature_src):
            os.makedirs(os.path.dirname(floating_feature_dst), exist_ok=True)
            shutil.copy2(floating_feature_src, floating_feature_dst)

        self._apply_floating_features()

        if self._config.get("tethering"):
            bpf_patch_dir = os.path.join(
                self.ws_root, "LumiROM", "Mods", "device_specific", "bpf_patch"
            )
            if LumiUtils.check_file(bpf_patch_dir):
                LumiUtils.merge_tree(bpf_patch_dir, self.firm_dir)

        ghost_system = os.path.join(self.firm_dir, "system", "system", "system")
        if LumiUtils.check_file(ghost_system):
            self.logger.info("  Cleaning up ghost triple-nested system directory...")
            LumiUtils.remove_path(ghost_system)

        fs_config_path = os.path.join(self.firm_dir, "config", "system_fs_config")
        if LumiUtils.check_file(fs_config_path):
            self.logger.info("  Purging triple-system corruption from fs_config...")
            with open(fs_config_path, "r", encoding="utf-8") as f:
                lines = [line for line in f if "system/system/system/" not in line]
            LumiUtils.replace_file_lines(fs_config_path, lines)

        stock_dir = os.path.join(devices_dir, device, "Stock")
        if LumiUtils.check_file(stock_dir):
            overlay_auto = os.path.join(self.firm_dir, "product", "overlay")
            if LumiUtils.check_file(overlay_auto):
                for f in os.listdir(overlay_auto):
                    if "auto_generated_rro_product" in f:
                        LumiUtils.remove_path(os.path.join(overlay_auto, f))
            for item in os.listdir(stock_dir):
                src = os.path.join(stock_dir, item)
                dst = os.path.join(self.firm_dir, item)
                if os.path.isdir(src):
                    LumiUtils.merge_tree(src, dst)
                elif os.path.isfile(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)

    def _apply_floating_features(self) -> None:
        floating_feature = os.path.join(
            self.firm_dir, "system", "system", "etc", "floating_feature.xml"
        )
        if not LumiUtils.check_file(floating_feature):
            return

        with open(floating_feature, "r") as f:
            content = f.read()

        features = {
            "SEC_FLOATING_FEATURE_COMMON_CONFIG_SEP_CATEGORY": "sep_basic",
            "SEC_FLOATING_FEATURE_COMMON_CONFIG_EDGE": "panel",
            "SEC_FLOATING_FEATURE_SYSTEMUI_SUPPORT_BRIEF_NOTIFICATION": "TRUE",
            "SEC_FLOATING_FEATURE_SYSTEMUI"
            "_CONFIG_EDGELIGHTING_FRAME_EFFECT": "frame_effect",
            "SEC_FLOATING_FEATURE_FRAMEWORK_SUPPORT_SCREEN_RECORDER": "TRUE",
            "SEC_FLOATING_FEATURE_AUDIO_SUPPORT_BT_RECORDING": "TRUE",
            "SEC_FLOATING_FEATURE_BATTERY_SUPPORT_BSOH_GALAXYDIAGNOSTICS": "TRUE",
            "SEC_FLOATING_FEATURE_SETTINGS_SUPPORT_DEFAULT_DOUBLE_TAP_TO_WAKE": "TRUE",
            "SEC_FLOATING_FEATURE_SETTINGS_SUPPORT_FUNCTION_KEY_MENU": "TRUE",
            "SEC_FLOATING_FEATURE_SYSTEM_SUPPORT_ENHANCED_CPU_RESPONSIVENESS": "TRUE",
            "SEC_FLOATING_FEATURE_SYSTEM_SUPPORT_ENHANCED_PROCESSING": "TRUE",
            "SEC_FLOATING_FEATURE_LAUNCHER_SUPPORT_CLOCK_LIVE_ICON": "TRUE",
            "SEC_FLOATING_FEATURE_LAUNCHER_CONFIG_ANIMATION_TYPE": "HighEnd",
            "SEC_FLOATING_FEATURE_CAMERA_CONFIG_STRIDE_OCR_VERSION": "V1",
            "SEC_FLOATING_FEATURE_CAMERA_SUPPORT_PRIVACY_TOGGLE": "TRUE",
            "SEC_FLOATING_FEATURE_GENAI_SUPPORT_IMAGE_CLIPPER": "TRUE",
            "SEC_FLOATING_FEATURE_GENAI_SUPPORT_OBJECT_ERASER": "TRUE",
            "SEC_FLOATING_FEATURE_GENAI_SUPPORT_REFLECTION_ERASER": "TRUE",
            "SEC_FLOATING_FEATURE_GENAI_SUPPORT_SHADOW_ERASER": "TRUE",
            "SEC_FLOATING_FEATURE_GENAI_SUPPORT_SMART_LASSO": "TRUE",
            "SEC_FLOATING_FEATURE_GENAI_SUPPORT_SPOT_FIXER": "TRUE",
            "SEC_FLOATING_FEATURE_GENAI_SUPPORT_STYLE_TRANSFER": "TRUE",
        }

        for key, value in features.items():
            pattern = rf"(<{key}>)(.*?)(</{key}>)"
            if not re.search(pattern, content):
                content = re.sub(
                    r"(<SEC_FLOATING_FEATURE_)",
                    f"    <{key}>{value}</{key}>\n    \\1",
                    content,
                )
            else:
                content = re.sub(pattern, rf"\g<1>{value}\g<3>", content)

        content = re.sub(
            r"<SEC_FLOATING_FEATURE_COMMON_DISABLE_NATIVE_AI>.*?</SEC_FLOATING_FEATURE_COMMON_DISABLE_NATIVE_AI>",
            "",
            content,
        )
        LumiUtils.replace_file(floating_feature, content)


class FeaturesApplierModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Applying features...")
        prop_files = [
            os.path.join(self.firm_dir, "product", "etc", "build.prop"),
            os.path.join(self.firm_dir, "vendor", "build.prop"),
            os.path.join(self.firm_dir, "system", "system", "build.prop"),
        ]

        build_props = self._load_properties_from_ini()
        build_props["ro.lumirom.official"] = (
            "true" if self._config.get("build_status") == "OFFICIAL" else "false"
        )

        for prop_file in prop_files:
            if not os.path.exists(prop_file):
                continue
            self._update_build_props(prop_file, build_props)

    def _load_properties_from_ini(self) -> Dict[str, str]:
        props = {}
        ini_path = os.path.join(self.ws_root, "config", "properties.ini")
        if LumiUtils.check_file(ini_path):
            config = configparser.ConfigParser()
            config.read(ini_path)
            for section in config.sections():
                for key, value in config.items(section):
                    props[key] = value
        return props

    def _update_build_props(self, prop_file: str, props: Dict[str, str]) -> None:
        with open(prop_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for key, value in props.items():
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(f"{key}="):
                    lines[i] = f"{key}={value}\n"
                    found = True
                    break

            if not found:
                lines.append(f"{key}={value}\n")

        LumiUtils.replace_file_lines(prop_file, lines)


class LumiBombsApplierModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Applying LumiBombs...")
        overlay_dir = os.path.join(self.ws_root, "LumiROM", "Mods", "overlays")

        if not LumiUtils.check_file(overlay_dir):
            self.logger.info("  No LumiBombs overlay found")
            return

        for mod in os.listdir(overlay_dir):
            mod_path = os.path.join(overlay_dir, mod)
            if not os.path.isdir(mod_path):
                continue
            self.logger.info("  Applying mod: %s", mod)
            LumiUtils.merge_tree(mod_path, self.firm_dir)

        self.logger.info("  LumiBombs applied")


class DisplayIdUpdaterModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Updating display ID...")
        version = self._config.get("version", "8.6.1")
        prop_files = [
            os.path.join(self.firm_dir, "product", "etc", "build.prop"),
            os.path.join(self.firm_dir, "system", "system", "build.prop"),
        ]

        suffix = f"LumiROM {version} UNOFFICIAL Stable"

        for prop_file in prop_files:
            if not os.path.exists(prop_file):
                continue

            with open(prop_file, "r") as f:
                content = f.read()

            if "ro.build.display.id=" in content:
                content = re.sub(
                    r"(ro\.build\.display\.id=)(.*)",
                    rf"\g<1>\g<2> - {suffix}",
                    content,
                )
                LumiUtils.replace_file(prop_file, content)
