import logging
import shutil
from typing import Optional

from .base_tool import BaseTool
from ..utils import LumiUtils

logger = logging.getLogger(__name__)


class Apktool(BaseTool):
    def __init__(
        self, jar_path: str, working_dir: Optional[str] = None, verbose: bool = False
    ):
        super().__init__(working_dir, verbose)
        self._jar = jar_path

    def decompile(self, file_path: str, output_dir: str) -> bool:
        """Decompile an APK or JAR file."""
        if LumiUtils.check_file(output_dir):
            shutil.rmtree(output_dir)

        args = ["java", "-jar", self._jar, "d", "-f", file_path, "-o", output_dir]
        result = self._run(args)
        return result.returncode == 0

    def recompile(
        self, decompiled_dir: str, framework_dir: str, output_path: str
    ) -> bool:
        """Recompile a decompiled directory into an APK or JAR."""
        args = [
            "java",
            "-jar",
            self._jar,
            "b",
            decompiled_dir,
            "--copy-original",
            "-p",
            framework_dir,
            "-o",
            output_path,
        ]
        result = self._run(args)
        return result.returncode == 0

    def install_framework(self, framework_path: str) -> bool:
        """Install a framework file for use in decompilation/recompilation."""
        args = ["java", "-jar", self._jar, "install-framework", framework_path]
        result = self._run(args)
        return result.returncode == 0
