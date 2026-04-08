import logging
from typing import Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Debugfs(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "debugfs"

    def dump(self, image: str, internal_path: str, local_path: str) -> bool:
        """Dump a file from a filesystem image using debugfs."""
        args = [
            self._binary,
            "-R",
            f"dump {internal_path} {local_path}",
            image,
        ]
        result = self._run(args)
        return result.returncode == 0
