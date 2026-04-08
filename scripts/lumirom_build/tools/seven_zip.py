import logging
from typing import List, Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class SevenZip(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "7z"

    def add(
        self,
        archive: str,
        files: List[str],
        compression_level: int = 1,
        extra_args: Optional[List[str]] = None,
    ) -> bool:
        """Add files to a 7z archive."""
        args = [self._binary, "a", f"-mx={compression_level}", "-mmt", archive]
        if extra_args:
            args.extend(extra_args)
        args.extend(files)

        result = self._run(args)
        return result.returncode == 0

    def list_contents(self, archive: str) -> Optional[str]:
        """List the contents of a 7z archive."""
        args = [self._binary, "l", "-slt", archive]
        result = self._run(args, capture_output=True)
        if result.returncode == 0:
            return result.stdout
        return None
