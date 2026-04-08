import logging
from typing import Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Img2Sdat(BaseTool):
    def __init__(
        self, binary_path: str, working_dir: Optional[str] = None, verbose: bool = False
    ):
        super().__init__(working_dir, verbose)
        self._binary = binary_path

    def convert(
        self, image_file: str, out_dir: str, map_file: Optional[str] = None
    ) -> bool:
        """Convert a raw image to a sparse android data archive (.new.dat)."""
        args = [self._binary, "-o", out_dir]
        if map_file:
            args.extend(["-B", map_file])
        args.append(image_file)

        result = self._run(args)
        return result.returncode == 0
