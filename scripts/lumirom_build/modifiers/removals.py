import os

from ..utils import LumiUtils
from .base_modifier import BaseModifier
from .constants import DEBLOAT_APPS


class IcccDeleterModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Deleting ICCC files...")
        targets = [
            "vendor/bin/hw/vendor.samsung.hardware.tlc.iccc@1.0-service",
            "vendor/etc/init/vendor.samsung.hardware.tlc.iccc@1.0-service.rc",
            "vendor/etc/vintf/manifest/vendor.samsung.hardware.tlc.iccc@1.0-manifest.xml",
            "vendor/lib64/vendor.samsung.hardware.tlc.iccc@1.0-impl.so",
            "vendor/lib64/vendor.samsung.hardware.tlc.iccc@1.0.so",
        ]
        LumiUtils.remove_targets(self.firm_dir, targets, self.logger)


class VendorDebloaterModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Debloating vendor...")
        targets = [
            "vendor/bin/create_factory_efs_file",
            "vendor/bin/factory",
            "vendor/bin/install-recovery.sh",
            "vendor/etc/factory.ini",
            "vendor/etc/init/vendor_flash_recovery.rc",
            "vendor/etc/mmigroup",
            "vendor/etc/recovery-resource.dat",
            "vendor/lib/modules",
            "vendor/lost+found",
            "vendor/recovery-from-boot.p",
            "vendor/res",
        ]
        LumiUtils.remove_targets(self.firm_dir, targets, self.logger)


class EsimRemoverModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Removing eSIM files...")
        targets = [
            "system/system/priv-app/EsimClient",
            "system/system/priv-app/EsimKeyString",
            "system/system/priv-app/EuiccService",
            "system/system/etc/permissions/privapp-permissions-com.samsung.euicc.xml",
            "system/system/etc/sysconfig/preinstalled-packages-com.samsung.euicc.xml",
            "system/system/etc/privapp-permissions-com.samsung.android.app.telephonyui.esimclient.xml",
            "system/system/etc/permissions/privapp-permissions-com.samsung.android.app.esimkeystring.xml",
            "system/system/etc/sysconfig/preinstalled-packages-com.samsung.android.app.esimkeystring.xml",
        ]
        LumiUtils.remove_targets(self.firm_dir, targets, self.logger)


class FabricCryptoRemoverModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Removing FabricCrypto...")
        targets = [
            "system/system/bin/fabric_crypto",
            "system/system/etc/init/fabric_crypto.rc",
            "system/system/etc/permissions/FabricCryptoLib.xml",
            "system/system/etc/vintf/manifest/fabric_crypto_manifest.xml",
            "system/system/framework/FabricCryptoLib.jar",
            "system/system/framework/oat/arm/FabricCryptoLib.odex",
            "system/system/framework/oat/arm/FabricCryptoLib.vdex",
            "system/system/framework/oat/arm64/FabricCryptoLib.odex",
            "system/system/framework/oat/arm64/FabricCryptoLib.vdex",
            "system/system/lib64/com.samsung.security.fabric.cryptod-V1-cpp.so",
            "system/system/lib64/vendor.samsung.hardware.security.fkeymaster-V1-ndk.so",
            "system/system/priv-app/KmxService",
        ]
        LumiUtils.remove_targets(self.firm_dir, targets, self.logger)


class JdmDebloatModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Applying JDM debloat...")
        devices_dir = os.path.join(self.ws_root, "LumiROM", "Devices")
        floating_feature = os.path.join(
            devices_dir, self.device, "floating_feature.xml"
        )
        is_jdm = False
        if os.path.exists(floating_feature):
            with open(floating_feature, "r") as f:
                content = f.read()
            if "jdm" in content.lower():
                is_jdm = True
        if is_jdm:
            self.logger.info("  JDM device detected, removing JDM bloat...")
            targets = [
                "system/system/app/BluetoothAgent",
                "system/system/app/BluetoothMidiService",
                "system/system/priv-app/SamsungCamera",
            ]
            LumiUtils.remove_targets(self.firm_dir, targets, self.logger)
        else:
            self.logger.info("  Not a JDM device, skipping JDM debloat")


class DeviceSpecificRemoverModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Removing device-specific files...")
        nfc_devices = ["SM-A225F", "SM-A225M"]
        if self.device in nfc_devices:
            self.logger.info("  Removing NFC libraries for %s...", self.device)
            nfc_files = [
                "system/system/lib64/libnfc-sec.so",
                "system/system/lib64/libnfc_sec_jni.so",
                "system/system/lib/libnfc_sec_jni.so",
            ]
            LumiUtils.remove_targets(self.firm_dir, nfc_files, self.logger)

        self.logger.info("  Removing unnecessary files...")
        targets = [
            "system/system/etc/init/boot-image.bprof",
            "system/system/etc/init/boot-image.prof",
            "system/system/hidden",
            "system/system/preload",
            "system/system/tts",
            "system/system/etc/mediasearch",
            "system/system/priv-app/MediaSearch",
        ]
        LumiUtils.remove_targets(self.firm_dir, targets, self.logger)


class DebloatAppsModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Debloating apps...")
        app_dirs = [
            os.path.join("system", "system", "app"),
            os.path.join("system", "system", "priv-app"),
            os.path.join("product", "app"),
            os.path.join("product", "priv-app"),
        ]

        removed = 0
        for app_dir in app_dirs:
            full_app_dir = os.path.join(self.firm_dir, app_dir)
            if not os.path.exists(full_app_dir):
                continue
            for app in DEBLOAT_APPS:
                app_path = os.path.join(full_app_dir, app)
                if os.path.exists(app_path):
                    LumiUtils.remove_path(app_path)
                    removed += 1
        self.logger.info("  Removed %d apps", removed)

        # Legacy catch-most for files that might have been duplicated
        # but overlap with specific removers
        esim_files = [
            "system/system/priv-app/EsimClient",
            "system/system/priv-app/EsimKeyString",
            "system/system/priv-app/EuiccService",
            "system/system/etc/permissions/privapp-permissions-com.samsung.euicc.xml",
            "system/system/etc/sysconfig/preinstalled-packages-com.samsung.euicc.xml",
            "system/system/etc/privapp-permissions-com.samsung.android.app.telephonyui.esimclient.xml",
            "system/system/etc/permissions/privapp-permissions-com.samsung.android.app.esimkeystring.xml",
            "system/system/etc/sysconfig/preinstalled-packages-com.samsung.android.app.esimkeystring.xml",
        ]
        LumiUtils.remove_targets(self.firm_dir, esim_files, self.logger)

        fabric_files = [
            "system/system/bin/fabric_crypto",
            "system/system/etc/init/fabric_crypto.rc",
            "system/system/etc/permissions/FabricCryptoLib.xml",
            "system/system/etc/vintf/manifest/fabric_crypto_manifest.xml",
            "system/system/framework/FabricCryptoLib.jar",
            "system/system/priv-app/KmxService",
        ]
        LumiUtils.remove_targets(self.firm_dir, fabric_files, self.logger)

        cleanup_files = [
            "system/system/etc/init/boot-image.bprof",
            "system/system/etc/init/boot-image.prof",
            "system/system/hidden",
            "system/system/preload",
            "system/system/tts",
            "system/system/etc/mediasearch",
            "system/system/priv-app/MediaSearch",
        ]
        LumiUtils.remove_targets(self.firm_dir, cleanup_files, self.logger)

        if self.device in ("SM-A225F", "SM-A225M"):
            nfc_files = [
                "system/system/lib64/libnfc-sec.so",
                "system/system/lib64/libnfc_sec_jni.so",
                "system/system/lib/libnfc_sec_jni.so",
            ]
            LumiUtils.remove_targets(self.firm_dir, nfc_files, self.logger)
