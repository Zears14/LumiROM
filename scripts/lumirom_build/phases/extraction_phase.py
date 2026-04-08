import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..exceptions import ExtractionError
from ..tools.aria2c import Aria2c
from ..tools.erofs import Erofs
from ..tools.file import File
from ..tools.simg2img import Simg2Img
from ..tools.tar import Tar
from ..modifiers.constants import FIRMWARE_URLS
from ..utils import LumiUtils
from .base_phase import BasePhase

logger = logging.getLogger(__name__)


class ExtractionPhase(BasePhase):
    PHASE_TAG = "EXTRACT"

    @property
    def name(self) -> str:
        return "Extraction"

    def execute(self) -> bool:
        self._download_firmware()
        self._extract_archive()
        self._prepare_partitions()
        self._extract_images()

        logger.info("Extraction phase complete")
        return True

    def _download_firmware(self) -> None:
        logger.debug(
            "Entering _download_firmware for device=%s", self._config.get("device")
        )
        logger.info("Downloading firmware...")
        device = self._config.get("device", "SM-A325F")
        firm_dir = self._config.get("firm_dir", "FIRMWARE")
        cache_dir = self._config.get("cache_dir", "./CACHE")
        verbose = self._config.get("verbose", False)

        os.makedirs(firm_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)

        base = self._get_device_base(device)
        url = self._get_fw_url(base)
        target = os.path.join(firm_dir, "BASE_FW.tar.zst")

        cache_file = os.path.join(cache_dir, f"{base}.tar.zst")
        if LumiUtils.check_file(cache_file):
            self._verify_base_firmware_hash(cache_file, base)
            logger.info("  Using cached firmware: %s", cache_file)
            shutil.copy2(cache_file, target)
        elif not LumiUtils.check_file(target):
            aria2 = Aria2c(self._config.get("ws_root", os.getcwd()), verbose)
            aria2.download(url, firm_dir, "BASE_FW.tar.zst")
            self._verify_base_firmware_hash(target, base)
            # Cache the downloaded file
            shutil.copy2(target, cache_file)
            logger.info("  Firmware cached to: %s", cache_file)
        else:
            self._verify_base_firmware_hash(target, base)

        vendor_url = f"https://github.com/Lumi-ROM/Vendors/releases/download/{device}_latest/vendor.img"
        vendor_target = os.path.join(firm_dir, "vendor.img")
        vendor_cache = os.path.join(cache_dir, f"{device}_vendor.img")
        if LumiUtils.check_file(vendor_cache):
            logger.info("  Using cached vendor: %s", vendor_cache)
            shutil.copy2(vendor_cache, vendor_target)
        elif not LumiUtils.check_file(vendor_target):
            logger.info("  Downloading vendor for %s...", device)
            aria2 = Aria2c(self._config.get("ws_root", os.getcwd()), verbose)
            try:
                aria2.download(
                    vendor_url, cache_dir, f"{device}_vendor.img", check_cert=False
                )
                if os.path.exists(os.path.join(cache_dir, f"{device}_vendor.img")):
                    shutil.copy2(
                        os.path.join(cache_dir, f"{device}_vendor.img"), vendor_target
                    )
            except Exception:
                # Expected failure for some devices without a vendor build
                logger.warning(
                    "Vendor download failed (may not exist for this device)",
                    exc_info=False,
                )

    def _extract_archive(self) -> None:
        firm_dir = self._config.get("firm_dir", "FIRMWARE")
        archive = os.path.join(firm_dir, "BASE_FW.tar.zst")

        if not LumiUtils.check_file(archive):
            raise ExtractionError(f"Archive not found: {archive}")

        logger.info("Extracting firmware archive...")
        verbose = self._config.get("verbose", False)
        tar = Tar(self._config.get("ws_root", os.getcwd()), verbose)
        tar.extract(archive, firm_dir, "zstd -d -T0")

        if LumiUtils.check_file(archive):
            os.remove(archive)

    def _prepare_partitions(self) -> None:
        firm_dir = self._config.get("firm_dir", "FIRMWARE")
        partitions = self._config.get(
            "partitions", "product,vendor,odm,system_ext,system"
        )
        keep = [p.strip() for p in partitions.split(",")]

        logger.info("Preparing partitions...")
        for item in os.listdir(firm_dir):
            item_path = os.path.join(firm_dir, item)
            base = item.replace(".img", "")

            if base not in keep:
                LumiUtils.remove_path(item_path)
                logger.info("  Removed: %s", item)
            else:
                logger.info("  Keeping: %s", item)

    def _extract_images(self) -> None:
        logger.debug("Entering _extract_images")
        firm_dir = self._config.get("firm_dir", "FIRMWARE")
        erofs_bin_dir = self._config.get("erofs_bin_dir", "bin/erofs-utils")
        ws_root = self._config.get("ws_root", os.getcwd())
        verbose = self._config.get("verbose", False)

        logger.info("Extracting images...")

        img_files = [
            f for f in os.listdir(firm_dir) if f.endswith(".img") and f != "boot.img"
        ]

        extract_jobs = []

        # 1. Unsparse sequentially to avoid resource contention (like shell script)
        for imgfile in img_files:
            img_path = os.path.join(firm_dir, imgfile)
            fstype = self._detect_filesystem(img_path)

            if fstype == "sparse":
                logger.info("  Unsparsing: %s...", imgfile)
                self._unsparse_image(img_path)
                fstype = self._detect_filesystem(img_path)

            extract_jobs.append((imgfile, img_path, fstype))

        erofs_jobs = [job for job in extract_jobs if job[2] == "erofs"]
        ext4_jobs = [job for job in extract_jobs if job[2] == "ext4"]
        unknown_jobs = [job for job in extract_jobs if job[2] not in {"erofs", "ext4"}]

        for imgfile, _, fstype in unknown_jobs:
            logger.warning(
                "  Unknown filesystem for %s, skipping (%s)", imgfile, fstype
            )

        erofs_job_limit = self._resolve_erofs_job_limit(len(erofs_jobs))
        erofs_threads = self._resolve_erofs_thread_count(erofs_job_limit)
        ext4_job_limit = self._resolve_ext4_job_limit(len(ext4_jobs))

        if erofs_jobs:
            logger.info(
                "  EROFS extraction plan: %s job(s) x %s thread(s)",
                erofs_job_limit,
                erofs_threads,
            )
            with ThreadPoolExecutor(max_workers=erofs_job_limit) as executor:
                futures = [
                    executor.submit(
                        self._extract_erofs,
                        job[0],
                        job[1],
                        firm_dir,
                        erofs_bin_dir,
                        ws_root,
                        verbose,
                        erofs_threads,
                    )
                    for job in erofs_jobs
                ]
                for future in as_completed(futures):
                    future.result()

        if ext4_jobs:
            logger.info("  ext4 extraction plan: %s job(s)", ext4_job_limit)
            with ThreadPoolExecutor(max_workers=ext4_job_limit) as executor:
                futures = [
                    executor.submit(self._extract_ext4_job, job, firm_dir, ws_root)
                    for job in ext4_jobs
                ]
                for future in as_completed(futures):
                    future.result()

        for imgfile in img_files:
            img_path = os.path.join(firm_dir, imgfile)
            LumiUtils.remove_path(img_path)

        for item in os.listdir(firm_dir):
            item_path = os.path.join(firm_dir, item)
            if os.path.isdir(item_path):
                LumiUtils.normalize_tree_permissions(item_path)

        logger.info("Image extraction complete")

    def _detect_filesystem(self, image_path: str) -> str:
        file_tool = File(verbose=self._config.get("verbose", False))
        info = file_tool.get_info(image_path)

        if "sparse" in info:
            return "sparse"
        elif "erofs" in info:
            return "erofs"
        elif "ext" in info or "linux" in info:
            return "ext4"
        return "unknown"

    def _unsparse_image(self, image_path: str) -> None:
        simg2img = Simg2Img(verbose=self._config.get("verbose", False))
        if simg2img.convert(image_path, f"{image_path}.raw"):
            shutil.move(f"{image_path}.raw", image_path)
        else:
            raise ExtractionError(f"Failed to unsparse: {image_path}")

    def _extract_ext4(self, image_path: str, output_dir: str, ws_root: str) -> None:
        extractor = os.path.join(ws_root, "bin/py_scripts/imgextractor.py")
        if os.path.exists(extractor):
            LumiUtils.run_or_stream(
                ["python3", extractor, image_path, output_dir],
                logger,
                stream=self._config.get("verbose", False),
                check=True,
            )

    def _extract_erofs(
        self,
        imgfile: str,
        img_path: str,
        output_dir: str,
        erofs_bin_dir: str,
        ws_root: str,
        verbose: bool,
        threads: int,
    ) -> None:
        logger.info("  Extracting EROFS: %s", imgfile)
        erofs = Erofs(erofs_bin_dir, ws_root, verbose)
        erofs.extract_with_threads(img_path, output_dir, threads)

    def _extract_ext4_job(self, job_data, output_dir: str, ws_root: str) -> None:
        imgfile, img_path, _ = job_data
        logger.info("  Extracting ext4: %s", imgfile)
        self._extract_ext4(img_path, output_dir, ws_root)

    def _resolve_erofs_job_limit(self, job_count: int) -> int:
        if job_count <= 0:
            return 1
        configured = self._get_performance_setting(
            "extract_erofs_jobs", fallback="auto"
        )
        if configured.lower() != "auto":
            try:
                return max(1, min(job_count, int(configured)))
            except ValueError:
                pass

        cpu_count = max(1, os.cpu_count() or 1)
        return min(job_count, max(1, min(2, cpu_count // 8 or 1)))

    def _resolve_erofs_thread_count(self, erofs_jobs: int) -> int:
        configured = self._get_performance_setting(
            "extract_erofs_threads", fallback="auto"
        )
        if configured.lower() != "auto":
            try:
                return max(1, int(configured))
            except ValueError:
                pass

        cpu_count = max(1, os.cpu_count() or 1)
        return max(1, min(24, cpu_count // max(1, erofs_jobs)))

    def _resolve_ext4_job_limit(self, job_count: int) -> int:
        if job_count <= 0:
            return 1
        configured = self._get_performance_setting("extract_ext4_jobs", fallback="auto")
        if configured.lower() != "auto":
            try:
                return max(1, min(job_count, int(configured)))
            except ValueError:
                pass

        cpu_count = max(1, os.cpu_count() or 1)
        return min(job_count, max(1, min(2, cpu_count // 4 or 1)))

    def _get_performance_setting(self, key: str, fallback: str) -> str:
        if self._config_loader is None:
            return fallback
        value = self._config_loader.get_build_setting(
            "performance", key, fallback=fallback
        )
        return str(value).strip()

    def _get_device_base(self, device: str) -> str:
        if any(x in device for x in ("A325", "M325")):
            return "A34"
        return "A24"

    def _get_fw_url(self, base: str) -> str:
        return FIRMWARE_URLS.get(base, "")

    def _verify_base_firmware_hash(self, archive_path: str, base: str) -> None:
        if self._config_loader is None:
            raise ExtractionError(
                "Config loader unavailable for firmware hash verification"
            )

        expected_hash = self._config_loader.get_build_setting(
            "fwhashes", base, fallback=""
        )
        expected_hash = str(expected_hash).strip().lower()
        if not expected_hash:
            raise ExtractionError(f"No configured firmware XXH128 hash for base {base}")

        actual_hash = LumiUtils.xxh128_file(archive_path)
        if actual_hash != expected_hash:
            raise ExtractionError(
                f"Firmware hash mismatch for {base}: "
                f"expected {expected_hash}, got {actual_hash} "
                f"({archive_path})"
            )
