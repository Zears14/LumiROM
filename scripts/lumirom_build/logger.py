import atexit
import logging
import logging.handlers
import os
import queue
import sys
import threading
from datetime import datetime, timezone


class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        # We handle padding manually here because the standard formatter
        # counts ANSI escape codes towards the width, which breaks alignment.

        # 1. Level Name (Fixed width: 8)
        levelname = record.levelname
        color = self.COLORS.get(levelname, "")
        record.levelname = f"{color}{levelname:<8}{self.RESET}"

        # 2. Module/Logger Name (Fixed width: 18)
        # Using record.module (filename) as it is usually shorter and cleaner
        orig_module = record.module
        if len(orig_module) > 18:
            module_display = orig_module[:15] + "..."
        else:
            module_display = f"{orig_module:<18}"
        record.module_padded = module_display

        result = super().format(record)

        # Restore original values to avoid side effects in other handlers (like file)
        record.levelname = levelname
        return result


_queue_listener = None
_queue_handler = None
_log_queue = None
_console_handler = None
_shared_file_handler = None
_log_filename = None
_logging_shutdown = False
_logger_lock = threading.RLock()


def setup_logging(verbose: bool = False) -> None:
    global _queue_listener, _queue_handler, _log_queue, _console_handler
    global _shared_file_handler, _log_filename

    # Guard: ensure handlers configured exactly once in the entry point
    if logging.root.handlers:
        return

    _log_queue = queue.Queue(-1)

    _console_handler = logging.StreamHandler(sys.stdout)
    # Using a cleaner, standardized format with fixed-width columns
    _console_handler.setFormatter(
        ColoredFormatter(
            "[\033[90m%(asctime)s\033[0m] %(levelname)s "
            "[\033[90m%(module_padded)s\033[0m] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    logs_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    _log_filename = f"build-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"

    _shared_file_handler = logging.FileHandler(os.path.join(logs_dir, _log_filename))
    _shared_file_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-8s [%(module)-18s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    _queue_listener = logging.handlers.QueueListener(
        _log_queue, _console_handler, _shared_file_handler, respect_handler_level=True
    )
    _queue_listener.start()

    _queue_handler = logging.handlers.QueueHandler(_log_queue)

    logging.root.setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.root.addHandler(_queue_handler)


def shutdown_logging() -> None:
    global _shared_file_handler, _log_filename, _logging_shutdown
    global _queue_listener, _queue_handler, _log_queue, _console_handler

    with _logger_lock:
        if _logging_shutdown:
            return
        _logging_shutdown = True

        if _queue_listener is not None:
            try:
                _queue_listener.stop()
            except Exception:
                pass

        for handler in (_console_handler, _shared_file_handler):
            if handler is None:
                continue
            try:
                handler.flush()
            except Exception:
                pass
            try:
                handler.close()
            except Exception:
                pass

        logging.root.handlers.clear()

        _queue_listener = None
        _queue_handler = None
        _log_queue = None
        _console_handler = None
        _shared_file_handler = None
        _log_filename = None


atexit.register(shutdown_logging)
