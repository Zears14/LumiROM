import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Optional

from .config_loader import ConfigLoader
from .exceptions import BuildError
from .phases.extraction_phase import ExtractionPhase
from .phases.modification_phase import ModificationPhase
from .phases.packaging_phase import PackagingPhase
from .utils import LumiUtils


@dataclass
class BuildConfig:
    device: str = "SM-A325F"
    verbose: bool = False
    tethering: bool = False
    cache_dir: str = "./CACHE"
    upload: bool = False
    ws_root: str = ""

    out_dir: str = field(init=False)
    tmp_dir: str = field(init=False)
    firm_dir: str = field(init=False)

    def __post_init__(self):
        ws_root = self.ws_root if self.ws_root else os.getcwd()
        self.ws_root = os.path.abspath(ws_root)
        self.cache_dir = os.path.abspath(self.cache_dir)
        self.out_dir = os.path.join(self.ws_root, "OUT")
        self.tmp_dir = os.path.join(self.ws_root, "TMP")
        self.firm_dir = os.path.join(self.ws_root, "FIRMWARE")

    def to_env(self) -> Dict[str, str]:
        env = os.environ.copy()

        # Determine status parity with shell IS_OFFICIAL
        official_hash = env.get("OFFICIAL_HASH", "")
        current_build = env.get("LUMIROM_BUILD", "")

        if official_hash and current_build:
            from .utils import LumiUtils

            status = LumiUtils.is_official(current_build, official_hash)
        else:
            status = "UNOFFICIAL"

        rom_tag = (
            "✨ LumiROM Official Build"
            if status == "OFFICIAL"
            else "🛠️ LumiROM Unofficial Build"
        )

        # Parity with GHA export
        github_env = env.get("GITHUB_ENV")
        if github_env:
            with open(github_env, "a") as f:
                f.write(f"BUILD_STATUS={status}\n")
                f.write(f"ROM_TAG={rom_tag}\n")

        env.update(
            {
                "STOCK_DEVICE": self.device,
                "USE_UI_8_TETHERING_APEX": "True" if self.tethering else "False",
                "OUTPUT_FILESYSTEM": "erofs",
                "LUMIROM_VERSION": "8.6.1",
                "OUT_DIR": self.out_dir,
                "TMP_DIR": self.tmp_dir,
                "WORK_DIR": "/dev/shm/WORK",
                "FIRM_DIR": self.firm_dir,
                "DEVICES_DIR": os.path.join(self.ws_root, "LumiROM/Devices"),
                "APKTOOL": os.path.join(self.ws_root, "bin/apktool/apktool.jar"),
                "VNDKS_COLLECTION": os.path.join(self.ws_root, "LumiROM/vndks"),
                "BUILD_PARTITIONS": "product,vendor,odm,system_ext,system",
                "LUMI_VERBOSE": "True" if self.verbose else "False",
                "BUILD_STATUS": status,
                "ROM_TAG": rom_tag,
            }
        )
        return env


class LumiROMBuilder:
    def __init__(
        self, config: BuildConfig, config_loader: Optional[ConfigLoader] = None
    ):
        self._cfg = config
        self._config_loader = config_loader or ConfigLoader("config")
        self._log = logging.getLogger(__name__)

    def build(self) -> bool:
        self._log.info("Starting LumiROM build for %s", self._cfg.device)
        self._log.info("Output: %s", self._cfg.out_dir)

        try:
            self._log.info("Checking dependencies...")
            self._setup_directories()
            self._log.info("  Directories created")
            self._log.info("  Cache directory: %s", self._cfg.cache_dir)

            self._log.info("=== EXTRACTION PHASE ===")
            if not self._run_phase(ExtractionPhase):
                raise BuildError("Extraction phase failed")

            self._log.info("=== MODIFICATION PHASE ===")
            if not self._run_phase(ModificationPhase):
                raise BuildError("Modification phase failed")

            self._log.info("=== PACKAGING PHASE ===")
            if not self._run_phase(PackagingPhase):
                raise BuildError("Packaging phase failed")

            self._checkpoint_cil_hashes_post_packaging()

            self._log.info("Build completed successfully!")
            self._log.info("  Final Output: %s/", self._cfg.out_dir)
            return True
        except BuildError as e:
            self._log.error("Build failed: %s", e)
            return False
        finally:
            self._cleanup()

    def _run_phase(self, phase_class) -> bool:
        phase_config = {
            "device": self._cfg.device,
            "firm_dir": self._cfg.firm_dir,
            "out_dir": self._cfg.out_dir,
            "tmp_dir": self._cfg.tmp_dir,
            "ws_root": self._cfg.ws_root,
            "cache_dir": self._cfg.cache_dir,
            "partitions": "product,vendor,odm,system_ext,system",
            "output_filesystem": "erofs",
            "erofs_bin_dir": "bin/erofs-utils",
            "apktool": "bin/apktool/apktool.jar",
            "tethering": self._cfg.tethering,
            "version": "8.6.1",
            "build_status": "UNOFFICIAL",
            "verbose": self._cfg.verbose,
        }
        phase = phase_class(phase_config, self._config_loader)
        return phase.execute()

    def _setup_directories(self) -> None:
        os.makedirs("/dev/shm/WORK", exist_ok=True)

        dirs_to_setup = ["FIRMWARE", "WORK", "OUT", "TMP"]
        for d in dirs_to_setup:
            path = os.path.join(self._cfg.ws_root, d)
            os.makedirs(path, exist_ok=True)

        os.makedirs(self._cfg.cache_dir, exist_ok=True)

    def _setup_cache(self) -> None:
        pass

    def _cleanup(self) -> None:
        work_dir = "/dev/shm/WORK"
        LumiUtils.remove_path(work_dir)

    def _checkpoint_cil_hashes_post_packaging(self) -> None:
        """Log xxhash128 of CIL files after packaging to detect corruption."""
        if not self._cfg.verbose:
            return

        self._log.info("  [CIL-CHECKPOINT:POST-PACKAGING]")
        LumiUtils.checkpoint_cil_hashes(self._cfg.firm_dir, self._log)

    @staticmethod
    def clean(clean_cache: bool = False, cache_dir: str = "./CACHE") -> None:
        log = logging.getLogger(__name__)
        log.info("Cleaning build environment...")
        transient_dirs = ["FIRMWARE", "WORK", "OUT", "TMP", "/dev/shm/WORK"]
        failed_paths = []
        for p in transient_dirs:
            if LumiUtils.check_file(p):
                try:
                    LumiUtils.remove_path(p)
                    log.info("  Removed: %s", p)
                except PermissionError:
                    failed_paths.append(p)

        if clean_cache and os.path.isdir(cache_dir):
            try:
                LumiUtils.remove_path(cache_dir)
                log.info("  Removed cache: %s/", cache_dir)
            except PermissionError:
                failed_paths.append(cache_dir)

        if failed_paths:
            from .sandbox import PodmanSandbox

            sandbox = PodmanSandbox(ConfigLoader("config"), os.getcwd())
            if sandbox.privileged_cleanup(failed_paths):
                for path in failed_paths:
                    if not LumiUtils.check_file(path):
                        log.info("  Removed via privileged sandbox: %s", path)
            else:
                raise BuildError(
                    "Failed to remove some paths without elevated access: "
                    + ", ".join(failed_paths)
                )

        log.info("Cleanup complete.")


def create_builder(
    device: str = "SM-A325F",
    verbose: bool = False,
    tethering: bool = False,
    cache_dir: str = "./CACHE",
) -> LumiROMBuilder:
    config = BuildConfig(
        device=device,
        verbose=verbose,
        tethering=tethering,
        cache_dir=cache_dir,
    )
    return LumiROMBuilder(config)
