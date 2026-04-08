import logging
from typing import List, Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Find(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "find"

    def find_directories(self, base_dir: str, name: str) -> List[str]:
        """Find directories matching a name."""
        args = [self._binary, base_dir, "-type", "d", "-name", name]
        result = self._run(args, capture_output=True)
        if result.returncode == 0 and result.stdout:
            return result.stdout.strip().split("\n")
        return []
