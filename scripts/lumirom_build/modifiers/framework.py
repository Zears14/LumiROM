import os
import shutil

from ..tools.apktool import Apktool
from ..tools.unzip import Unzip
from ..utils import LumiUtils
from .base_modifier import BaseModifier


class FrameworkInstallerModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Installing framework...")
        framework_res = os.path.join(
            self.firm_dir, "system", "system", "framework", "framework-res.apk"
        )
        fallback_res = os.path.join(self.ws_root, "bin", "framework-res.apk")
        apktool_jar = os.path.join(self.ws_root, "bin", "apktool", "apktool.jar")

        if not LumiUtils.check_file(framework_res):
            self.logger.warning("  Framework-res not found: %s", framework_res)
            return

        unzip_tool = Unzip(verbose=self._config.get("verbose", False))
        if not unzip_tool.test(framework_res):
            self.logger.info("  Framework-res integrity check failed, using fallback")
            if os.path.exists(fallback_res):
                shutil.copy2(fallback_res, framework_res)

        if LumiUtils.check_file(apktool_jar):
            self.logger.info("  Installing framework...")
            apk_tool = Apktool(apktool_jar, verbose=self._config.get("verbose", False))
            apk_tool.install_framework(framework_res)


class FrameworkPatcherModifier(BaseModifier):
    def apply(self) -> None:
        self.logger.info("Patching framework...")
        apktool = os.path.join(
            self.ws_root, self._config.get("apktool", "bin/apktool/apktool.jar")
        )
        work_dir = self.tmp_dir
        os.makedirs(work_dir, exist_ok=True)

        framework_res = os.path.join(
            self.firm_dir, "system", "system", "framework", "framework-res.apk"
        )
        unzip_tool = Unzip(verbose=self._config.get("verbose", False))
        if LumiUtils.check_file(framework_res):
            if not unzip_tool.test(framework_res):
                fallback = os.path.join(self.ws_root, "bin", "framework-res.apk")
                if LumiUtils.check_file(fallback):
                    shutil.copy2(fallback, framework_res)

        apk_tool = Apktool(apktool, verbose=self._config.get("verbose", False))
        apk_tool.install_framework(framework_res)

        ssrm_dir = os.path.join(work_dir, "ssrm")
        services_dir = os.path.join(work_dir, "services")

        ssrm_jar = os.path.join(
            self.firm_dir, "system", "system", "framework", "ssrm.jar"
        )
        if LumiUtils.check_file(ssrm_jar):
            apk_tool.decompile(ssrm_jar, ssrm_dir)

        services_jar = os.path.join(
            self.firm_dir, "system", "system", "framework", "services.jar"
        )
        if LumiUtils.check_file(services_jar):
            apk_tool.decompile(services_jar, services_dir)

        if LumiUtils.check_file(ssrm_dir):
            self._patch_ssrm(ssrm_dir)

        if LumiUtils.check_file(services_dir):
            self._patch_services(services_dir)

        if LumiUtils.check_file(ssrm_dir):
            apk_tool.recompile(
                ssrm_dir, work_dir, os.path.join(work_dir, "ssrm_built.jar")
            )
            shutil.copy2(os.path.join(work_dir, "ssrm_built.jar"), ssrm_jar)

        if LumiUtils.check_file(services_dir):
            apk_tool.recompile(
                services_dir,
                work_dir,
                os.path.join(work_dir, "services_built.jar"),
            )
            shutil.copy2(os.path.join(work_dir, "services_built.jar"), services_jar)

    def _patch_ssrm(self, ssrm_dir: str) -> None:
        pass

    def _patch_services(self, services_dir: str) -> None:
        pass
