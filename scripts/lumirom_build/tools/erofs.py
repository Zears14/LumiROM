import logging
import os
from typing import Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Erofs(BaseTool):
    def __init__(
        self, binary_dir: str, working_dir: Optional[str] = None, verbose: bool = False
    ):
        super().__init__(working_dir, verbose)
        self._extract_binary = os.path.join(binary_dir, "extract.erofs")
        self._mkfs_binary = os.path.join(binary_dir, "mkfs.erofs")

    def extract(self, image: str, output_dir: str, force: bool = True) -> None:
        args = [
            self._extract_binary,
            "-i",
            image,
            "-x",
            "-f" if force else "",
            "-o",
            output_dir,
        ]
        args = [arg for arg in args if arg]

        logger.debug(
            "Executing EROFS extraction for image=%s to output_dir=%s: %s",
            image,
            output_dir,
            " ".join(args),
        )

        result = self._run(args)
        if result.returncode != 0:
            logger.error("Extraction failed for image=%s: %s", image, result.stderr)
            raise RuntimeError(f"erofs extraction failed: {result.stderr}")

    def extract_with_threads(
        self, image: str, output_dir: str, threads: int, force: bool = True
    ) -> None:
        args = [
            self._extract_binary,
            "-i",
            image,
            "-x",
            "-f" if force else "",
            f"-T{threads}" if threads > 0 else "",
            "-o",
            output_dir,
        ]
        args = [arg for arg in args if arg]

        logger.debug(
            "Executing threaded EROFS extraction threads=%d image=%s to "
            "output_dir=%s: %s",
            threads,
            image,
            output_dir,
            " ".join(args),
        )

        result = self._run(args)
        if result.returncode != 0:
            logger.error(
                "Threaded extraction failed for image=%s: %s", image, result.stderr
            )
            raise RuntimeError(f"erofs extraction failed: {result.stderr}")

    def create(self, image: str, source_dir: str, force: bool = True) -> None:
        args = [
            self._mkfs_binary,
            "-f" if force else "",
            "-p",
            "erofs",
            "-o",
            image,
            source_dir,
        ]
        args = [arg for arg in args if arg]

        logger.debug(
            "Executing EROFS creation image=%s from source_dir=%s: %s",
            image,
            source_dir,
            " ".join(args),
        )

        result = self._run(args)
        if result.returncode != 0:
            logger.error("Creation failed for image=%s: %s", image, result.stderr)
            raise RuntimeError(f"erofs creation failed: {result.stderr}")
