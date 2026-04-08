import logging
from typing import Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Xxd(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "xxd"

    def dump(self, file_path: str) -> str:
        """Hex-dump a file into a plain string."""
        args = [self._binary, "-p", "-c", "0", file_path]
        result = self._run(args, capture_output=True)
        if result.returncode == 0:
            return result.stdout.strip()
        return ""
