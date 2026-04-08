import logging
import os
from typing import Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Tar(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "tar"

    def extract(
        self,
        archive: str,
        destination: Optional[str] = None,
        decompressor: Optional[str] = None,
    ) -> None:
        args = [self._binary]

        if decompressor:
            args.extend(["--use-compress-program", decompressor])

        args.extend(["-xf", archive])

        if destination:
            args.extend(["-C", destination])

        logger.debug(
            "Executing tar extraction archive=%s using decompressor=%s: %s",
            archive,
            decompressor,
            " ".join(args),
        )

        result = self._run(args)
        if result.returncode != 0:
            logger.error(
                "Tar extraction failed for archive=%s: %s", archive, result.stderr
            )
            raise RuntimeError(f"tar extraction failed: {result.stderr}")

    def create(
        self, archive: str, source: str, compressor: Optional[str] = None
    ) -> None:
        args = [self._binary]

        if compressor:
            args.extend(["--use-compress-program", compressor])

        args.extend(
            [
                "-cf",
                archive,
                "-C",
                os.path.dirname(source) or ".",
                os.path.basename(source),
            ]
        )

        logger.debug(
            "Executing tar creation archive=%s from source=%s: %s",
            archive,
            source,
            " ".join(args),
        )

        result = self._run(args)
        if result.returncode != 0:
            logger.error(
                "Tar creation failed for archive=%s: %s", archive, result.stderr
            )
            raise RuntimeError(f"tar creation failed: {result.stderr}")
