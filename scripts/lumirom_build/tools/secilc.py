import logging
from typing import List, Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Secilc(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "secilc"

    def compile(
        self,
        cil_files: List[str],
        vndk_version: int,
        output_policy: str = "/dev/null",
        file_contexts: str = "/dev/null",
    ) -> bool:
        """Compile SELinux CIL files into a binary policy."""
        args = (
            [self._binary]
            + cil_files
            + [
                "-m",
                "-M",
                "true",
                "-G",
                "-N",
                "-c",
                str(vndk_version),
                "-o",
                output_policy,
                "-f",
                file_contexts,
            ]
        )
        result = self._run(args)
        return result.returncode == 0
