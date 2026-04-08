import logging
from typing import Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Simg2Img(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "simg2img"

    def convert(self, sparse_img: str, out_img: str) -> bool:
        """Convert a sparse Android image to a raw image."""
        args = [self._binary, sparse_img, out_img]
        result = self._run(args)
        return result.returncode == 0
