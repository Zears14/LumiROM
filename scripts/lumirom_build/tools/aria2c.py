import logging
from typing import Optional

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class Aria2c(BaseTool):
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        super().__init__(working_dir, verbose)
        self._binary = "aria2c"

    def download(
        self,
        url: str,
        output_dir: str,
        filename: Optional[str] = None,
        connections: int = 16,
        check_cert: bool = True,
    ) -> None:
        args = [
            self._binary,
            "-x",
            str(connections),
            "-d",
            output_dir,
        ]

        if filename:
            args.extend(["-o", filename])

        if not check_cert:
            args.append("--check-certificate=false")

        args.extend(["--allow-overwrite=true", "--auto-file-renaming=false", url])

        logger.debug(
            "Command executed: %s, checking certificate: %s", " ".join(args), check_cert
        )

        result = self._run(args)
        if result.returncode != 0:
            logger.error("Download failed to fetch %s: %s", url, result.stderr)
            raise RuntimeError(f"aria2c failed: {result.stderr}")
