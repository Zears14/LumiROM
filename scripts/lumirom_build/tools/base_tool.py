import os
import subprocess
from typing import List, Optional


class BaseTool:
    def __init__(self, working_dir: Optional[str] = None, verbose: bool = False):
        self._working_dir = working_dir or os.getcwd()
        self._verbose = verbose

    def _run(
        self,
        args: List[str],
        check: bool = False,
        capture_output: Optional[bool] = None,
    ) -> subprocess.CompletedProcess:
        should_capture = True if capture_output is None else capture_output
        stream_it = self._verbose and not should_capture
        import logging

        from ..utils import LumiUtils

        logger_obj = logging.getLogger(self.__class__.__module__)
        return LumiUtils.run_or_stream(
            args,
            logger_obj,
            stream=stream_it,
            cwd=self._working_dir,
            check=check,
            capture_output=should_capture,
        )

    def exists(self) -> bool:
        return True
