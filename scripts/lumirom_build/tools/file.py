import logging
from typing import Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class File(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "file"

    def get_info(self, file_path: str) -> str:
        """Get the file type information using the 'file' command."""
        args = [self._binary, "-b", file_path]
        result = self._run(args, capture_output=True)
        if result.returncode == 0:
            return result.stdout.strip().lower()
        return ""
