import logging
from typing import List, Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Unzip(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "unzip"

    def test(self, archive: str) -> bool:
        """Check the integrity of the zip archive."""
        args = [self._binary, "-t", archive]
        result = self._run(args, capture_output=True)
        return result.returncode == 0

    def extract(
        self,
        archive: str,
        files: Optional[List[str]] = None,
        destination: Optional[str] = None,
        overwrite: bool = True,
    ) -> bool:
        """Extract files from the archive."""
        args = [self._binary]
        if overwrite:
            args.append("-o")
        else:
            args.append("-n")

        args.append(archive)

        if files:
            args.extend(files)

        if destination:
            args.extend(["-d", destination])

        result = self._run(args)
        return result.returncode == 0
