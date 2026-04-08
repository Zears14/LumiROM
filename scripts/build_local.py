#!/usr/bin/env python3
"""
LumiROM Local Build System
Uses the new Python build modules
"""

import argparse
import os
import sys
import signal
from datetime import datetime
import logging

MIN_PYTHON = (3, 10)


def _require_python_version() -> None:
    if sys.version_info >= MIN_PYTHON:
        return

    version = ".".join(str(part) for part in MIN_PYTHON)
    current = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    sys.stderr.write(
        f"LumiROM build system requires Python {version}+; found {current}.\n"
    )
    raise SystemExit(1)


_require_python_version()

SCRIPT_PATH = os.path.realpath(__file__)
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_PATH))
sys.path.insert(0, REPO_ROOT)

from scripts.lumirom_build.builder import BuildConfig, LumiROMBuilder  # noqa: E402
from scripts.lumirom_build.preflight import PreflightChecker  # noqa: E402
from scripts.lumirom_build.config_loader import ConfigLoader  # noqa: E402
from scripts.lumirom_build.logger import setup_logging, shutdown_logging  # noqa: E402
from scripts.lumirom_build.sandbox import PodmanSandbox  # noqa: E402

logger = logging.getLogger(__name__)


def _die(msg: str, code: int = 1) -> None:
    logger.error("[!] %s", msg)
    sys.exit(code)


def _signal_handler(sig, frame) -> None:
    sys.stdout.write("\033[2E\r\033[K")
    sys.stdout.flush()
    logger.info("[!] Build interrupted. Cleaning up...")
    LumiROMBuilder.clean()
    sys.exit(130)


def _interactive_config(defaults: BuildConfig) -> BuildConfig:
    logger.info("\n>>> Interactive Build Setup")
    devices = sorted(os.listdir("LumiROM/Devices"))
    logger.info("    Available models: %s", ", ".join(devices))

    device = input(f"    Device model [{defaults.device}]: ").strip() or defaults.device
    tethering = input("    UI 8.5 Tethering patch? (y/N): ").strip().lower() == "y"
    verbose = input("    Verbose output? (y/N): ").strip().lower() == "y"
    upload = input("    Upload after build? (y/N): ").strip().lower() == "y"
    print()

    return BuildConfig(
        device=device,
        verbose=verbose,
        tethering=tethering,
        cache_dir=defaults.cache_dir,
        upload=upload,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LumiROM Build System")
    sub = parser.add_subparsers(dest="command", required=True)

    bp = sub.add_parser("lumirom", help="Execute the ROM build pipeline")
    bp.add_argument(
        "-d", "--device", default="SM-A325F", help="Device model (default: SM-A325F)"
    )
    bp.add_argument(
        "-v", "--verbose", action="store_true", help="Show full command output"
    )
    bp.add_argument(
        "-c",
        "--cache",
        default="./CACHE",
        help="Firmware cache directory (default: ./CACHE)",
    )
    bp.add_argument(
        "-t",
        "--tethering",
        action="store_true",
        help="Enable UI 8.5 Tethering APEX patch",
    )
    bp.add_argument(
        "--upload",
        action="store_true",
        help="Upload result to Hugging Face after build",
    )
    bp.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactively configure the build",
    )
    bp.add_argument(
        "--no-sandbox",
        action="store_true",
        help="Run directly on the host instead of inside the default Podman sandbox",
    )

    cp = sub.add_parser("clean", help="Purge temporary build files")
    cp.add_argument(
        "--clean-cache", action="store_true", help="Also remove the firmware cache"
    )
    cp.add_argument(
        "-c", "--cache", default="./CACHE", help="Cache directory (default: ./CACHE)"
    )

    return parser


def main() -> None:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    PreflightChecker.check_repo_root()

    args = _build_arg_parser().parse_args()
    config_loader = ConfigLoader("config")

    if args.command == "clean":
        LumiROMBuilder.clean(clean_cache=args.clean_cache, cache_dir=args.cache)
        return

    setup_logging(args.verbose)

    ws_root = os.getcwd()
    preflight = PreflightChecker(config_loader)
    sandbox = PodmanSandbox(config_loader, ws_root)
    config = BuildConfig(
        device=args.device,
        verbose=args.verbose,
        tethering=args.tethering,
        cache_dir=args.cache,
        upload=args.upload,
        ws_root=ws_root,
    )

    if args.interactive:
        config = _interactive_config(config)

    preflight.check_device_config(config.device)
    PreflightChecker.check_workspace_clean()

    if args.command == "lumirom" and not args.no_sandbox and sandbox.should_wrap():
        preflight.check_sandbox_host_environment(
            config.ws_root, config.cache_dir, sandbox
        )
        logger.info("Launching Podman sandbox...")
        try:
            sys.exit(sandbox.run(sys.argv[1:]))
        except RuntimeError as exc:
            _die(str(exc))

    preflight.check_local_environment(config.ws_root, config.cache_dir)

    builder = LumiROMBuilder(config)
    start = datetime.now()
    success = builder.build()
    logger.info("Elapsed: %s", datetime.now() - start)

    if success and config.upload:
        logger.info("\n>>> Starting upload...")
        upload_script = os.path.join("scripts", "upload_local.py")
        import subprocess

        subprocess.run([sys.executable, upload_script], check=False)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutdown_logging()
