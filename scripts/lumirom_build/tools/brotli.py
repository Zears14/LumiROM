import logging
from typing import Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Brotli(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "brotli"

    def compress(self, input_file: str, output_file: str, quality: int = 6) -> bool:
        """Compress a file using brotli."""
        args = [
            self._binary,
            "-f",
            "-q",
            str(quality),
            f"--output={output_file}",
            input_file,
        ]
        result = self._run(args)
        return result.returncode == 0
