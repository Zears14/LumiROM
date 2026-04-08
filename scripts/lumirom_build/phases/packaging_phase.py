import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from ..exceptions import PackagingError
from ..modifiers.constants import DEVICE_CODENAMES
from ..tools.brotli import Brotli
from ..tools.img2sdat import Img2Sdat
from ..tools.seven_zip import SevenZip
from ..utils import LumiUtils
from .base_phase import BasePhase

logger = logging.getLogger(__name__)


class PackagingPhase(BasePhase):
    PHASE_TAG = "PACKAGE"

    @property
    def name(self) -> str:
        return "Packaging"

    def execute(self) -> bool:
        self._init_zip_workspace()
        self._build_images()
        self._update_metadata()
        self._create_zip()

        logger.info("Packaging phase complete")
        return True

    def _init_zip_workspace(self) -> None:
        out_dir = self._config.get("out_dir", "OUT")
        ws_root = self._config.get("ws_root", os.getcwd())
        template_dir = os.path.join(ws_root, "template")
        zip_work_dir = os.path.join(out_dir, "ZIP_PACKAGE")

        os.makedirs(out_dir, exist_ok=True)

        if not LumiUtils.check_file(zip_work_dir):
            os.makedirs(zip_work_dir)
            if LumiUtils.check_file(template_dir):
                LumiUtils.merge_tree(template_dir, zip_work_dir)

        boot_img_src = os.path.join(
            ws_root,
            "LumiROM",
            "Devices",
            self._config.get("device", "SM-A325F"),
            "boot.img",
        )
        if LumiUtils.check_file(boot_img_src):
            shutil.copy2(boot_img_src, os.path.join(zip_work_dir, "boot.img"))

    def _build_images(self) -> None:
        firm_dir = self._config.get("firm_dir", "FIRMWARE")
        out_dir = self._config.get("out_dir", "OUT")
        tmp_dir = self._config.get("tmp_dir", "TMP") or "/dev/shm/WORK"
        ws_root = self._config.get("ws_root", os.getcwd())
        erofs_utils = os.path.join(ws_root, "bin", "erofs-utils")
        img2sdat = os.path.join(ws_root, "bin", "img2sdat", "img2sdat")
        mkfs_workers = self._resolve_mkfs_workers()
        package_workers = self._resolve_package_workers()
        fast_img2sdat = (
            self._config_loader.get_build_setting_bool(
                "performance", "fast_img2sdat", fallback=True
            )
            if self._config_loader
            else True
        )
        erofs_compressor = self._get_performance_setting(
            "erofs_compressor", fallback="lz4"
        )
        brotli_quality = self._resolve_quality_setting(
            "brotli_quality", fallback=1, minimum=0, maximum=11
        )

        os.makedirs(tmp_dir, exist_ok=True)

        partitions = [
            d
            for d in os.listdir(firm_dir)
            if os.path.isdir(os.path.join(firm_dir, d)) and d != "config"
        ]

        class ContextAdapter(logging.LoggerAdapter):
            def process(self, msg, kwargs):
                # Ensure partition tag is always 12 chars for alignment
                # (max: [system_ext])
                ctx = f"[{self.extra['context']}]"
                return f"{ctx:<12} {msg}", kwargs

        def build_partition(partition: str) -> None:
            plog = ContextAdapter(logger, {"context": partition})
            plog.info("Building partition...")

            partition_dir = os.path.join(firm_dir, partition)

            if not LumiUtils.check_file(partition_dir):
                raise PackagingError(f"Partition dir does not exist: {partition_dir}")

            item_count = sum(1 for _ in os.scandir(partition_dir))
            if item_count == 0:
                raise PackagingError(f"Partition dir is empty: {partition_dir}")
            plog.info("  Partition has %d items", item_count)

            fs_config = os.path.join(firm_dir, "config", f"{partition}_fs_config")
            file_contexts = os.path.join(
                firm_dir, "config", f"{partition}_file_contexts"
            )
            out_img = os.path.join(out_dir, f"{partition}.img")

            self._generate_fs_config(partition_dir, partition, fs_config)
            self._generate_file_contexts(partition_dir, partition, file_contexts)

            for config_path in (file_contexts, fs_config):
                LumiUtils.sort_unique_file(config_path)

            mkfs_erofs = os.path.join(erofs_utils, "mkfs.erofs")
            if not LumiUtils.check_file(mkfs_erofs):
                raise PackagingError(f"mkfs.erofs not found: {mkfs_erofs}")

            result = LumiUtils.run_or_stream(
                [
                    mkfs_erofs,
                    "--mount-point",
                    f"/{partition}",
                    "--fs-config-file",
                    fs_config,
                    "--file-contexts",
                    file_contexts,
                    "--workers",
                    str(mkfs_workers),
                    "-z",
                    erofs_compressor,
                    "-b",
                    "4096",
                    "-T",
                    str(int(datetime.now().timestamp())),
                    out_img,
                    partition_dir,
                ],
                plog,
                stream=self._config.get("verbose", False),
            )
            if result.returncode != 0:
                plog.warning("  mkfs.erofs failed (exit %d)", result.returncode)
                if result.stderr:
                    for line in result.stderr.strip().splitlines():
                        plog.warning("    stderr: %s", line)
                if result.stdout:
                    for line in result.stdout.strip().splitlines():
                        plog.info("    stdout: %s", line)
                raise PackagingError(f"mkfs.erofs failed for {partition}")

            img_size_mb = os.path.getsize(out_img) // 1024 // 1024
            plog.info("  Created %s.img (%dMB)", partition, img_size_mb)

            patch_dat = os.path.join(tmp_dir, f"{partition}.patch.dat")
            with open(patch_dat, "a", encoding="utf-8"):
                pass

            br_file = os.path.join(tmp_dir, f"{partition}.new.dat.br")
            brotli_tool = Brotli(verbose=self._config.get("verbose", False))
            if fast_img2sdat and self._can_use_fast_img2sdat(out_img):
                self._write_full_transfer_list(partition, out_img, tmp_dir)
                if not brotli_tool.compress(out_img, br_file, quality=brotli_quality):
                    raise PackagingError(f"brotli compression failed for {partition}")
            else:
                img_to_sdat = Img2Sdat(
                    img2sdat, verbose=self._config.get("verbose", False)
                )
                map_file = os.path.join(tmp_dir, f"{partition}.map")
                if not img_to_sdat.convert(out_img, tmp_dir, map_file):
                    raise PackagingError(f"img2sdat failed for {partition}")

                dat_file = os.path.join(tmp_dir, f"{partition}.new.dat")
                if not LumiUtils.check_file(dat_file):
                    raise PackagingError(
                        f"img2sdat failed for {partition} (missing .new.dat)"
                    )

                if not brotli_tool.compress(dat_file, br_file, quality=brotli_quality):
                    raise PackagingError(f"brotli compression failed for {partition}")
                LumiUtils.remove_path(dat_file)

            plog.info("  Complete")

        logger.info(
            "  Build plan: %s partition job(s), mkfs.erofs --workers=%s, "
            "compressor=%s, brotli-q=%s",
            package_workers,
            mkfs_workers,
            erofs_compressor,
            brotli_quality,
        )

        with ThreadPoolExecutor(max_workers=package_workers) as executor:
            list(executor.map(build_partition, partitions))

        self._update_op_list()

    def _generate_fs_config(
        self, partition_dir: str, partition: str, fs_config_path: str
    ) -> None:
        lines = []
        existing = set()
        repaired_count = 0
        dropped_count = 0

        if partition == "vendor" and LumiUtils.check_file(fs_config_path):
            with open(fs_config_path, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        path_entry = parts[0]
                        if path_entry.startswith("/"):
                            path_entry = path_entry[1:]
                        if len(parts[3]) == 4 and parts[3].startswith("0"):
                            parts[3] = parts[3][1:]
                        if path_entry.startswith("vendor") or path_entry.startswith(
                            "lost"
                        ):
                            line_str = (
                                f"{path_entry} {parts[1]} {parts[2]} {parts[3]}\n"
                            )
                            existing.add(path_entry)
                            lines.append(line_str)

            for extra in [
                "/ 0 2000 755\n",
                "vendor/lost+found 0 0 700\n",
                "vendor/bin/toolbox 0 2000 755\n",
            ]:
                parts = extra.strip().split()
                if parts[0] not in existing:
                    existing.add(parts[0])
                    lines.append(extra)
        else:
            if LumiUtils.check_file(fs_config_path):
                with open(fs_config_path, "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            path_entry = self._canonicalize_partition_entry(
                                parts[0], partition_dir, partition
                            )
                            if path_entry is None:
                                dropped_count += 1
                                continue
                            if path_entry != parts[0].rstrip("/"):
                                repaired_count += 1
                            if path_entry not in existing:
                                lines.append(f"{path_entry} {' '.join(parts[1:])}\n")
                                existing.add(path_entry)

            if not os.path.exists(fs_config_path) and partition not in existing:
                lines.append(f"{partition} 0 0 0755\n")
                existing.add(partition)

        root_entry = "/ 0 2000 0755\n" if partition == "vendor" else "/ 0 0 0755\n"
        if "/" not in existing:
            lines.insert(0, root_entry)
            existing.add("/")

        added_count = 0
        for root, dirs, files in os.walk(partition_dir):
            for name in files:
                rel_path = os.path.relpath(os.path.join(root, name), partition_dir)
                clean_path = self._strip_partition_prefix(rel_path, partition)
                if clean_path not in existing:
                    full_path = os.path.join(root, name)
                    if os.access(full_path, os.X_OK):
                        lines.append(f"{clean_path} 0 0 0755\n")
                    else:
                        lines.append(f"{clean_path} 0 0 0644\n")
                    existing.add(clean_path)
                    added_count += 1
            for name in dirs:
                rel_path = os.path.relpath(os.path.join(root, name), partition_dir)
                clean_path = self._strip_partition_prefix(rel_path, partition)
                if clean_path not in existing:
                    lines.append(f"{clean_path} 0 0 0755\n")
                    existing.add(clean_path)
                    added_count += 1

        content = "".join(lines)
        LumiUtils.replace_file(fs_config_path, content)
        logger.info(
            "  fs_config: %d entries for %s (added %d, repaired %d, dropped %d)",
            len(lines),
            partition,
            added_count,
            repaired_count,
            dropped_count,
        )

    def _strip_partition_prefix(self, path: str, partition: str) -> str:
        if path == "/":
            return path
        return f"{partition}/{path}"

    def _generate_file_contexts(
        self, partition_dir: str, partition: str, file_contexts_path: str
    ) -> None:
        context = "u:object_r:system_file:s0"
        if partition == "vendor":
            context = "u:object_r:vendor_file:s0"

        lines = []
        existing = set()
        added_count = 0
        repaired_count = 0
        dropped_count = 0

        if LumiUtils.check_file(file_contexts_path):
            with open(file_contexts_path, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        raw_path = parts[0]
                        literal_path = raw_path.replace("\\", "")
                        path_entry = self._canonicalize_partition_entry(
                            literal_path, partition_dir, partition
                        )
                        if path_entry is None and self._is_file_context_pattern(
                            raw_path
                        ):
                            lines.append(line)
                            existing.add(literal_path)
                            continue
                        if path_entry is None:
                            dropped_count += 1
                            continue
                        if path_entry != literal_path:
                            repaired_count += 1
                        if path_entry not in existing:
                            lines.append(
                                f"{self._escape_file_context_path(path_entry)} "
                                f"{' '.join(parts[1:])}\n"
                            )
                            existing.add(path_entry)

        for root, dirs, files in os.walk(partition_dir):
            for name in files + [d.rstrip("/") for d in dirs]:
                rel_path = os.path.relpath(os.path.join(root, name), partition_dir)
                path_entry = f"/{partition}/{rel_path}"
                if path_entry not in existing:
                    file_context = context
                    if partition in ["system", "product"]:
                        if name.endswith(".so"):
                            file_context = "u:object_r:system_lib_file:s0"
                        else:
                            file_context = "u:object_r:system_file:s0"

                    escaped_path = self._escape_file_context_path(path_entry)
                    lines.append(f"{escaped_path} {file_context}\n")
                    existing.add(path_entry)
                    added_count += 1

        content = "".join(lines)
        LumiUtils.replace_file(file_contexts_path, content)
        logger.info(
            "  file_contexts: %d entries for %s (added %d, repaired %d, dropped %d)",
            len(lines),
            partition,
            added_count,
            repaired_count,
            dropped_count,
        )

    def _canonicalize_partition_entry(
        self, path_entry: str, partition_dir: str, partition: str
    ) -> str | None:
        path_entry = path_entry.rstrip("/")
        is_absolute = path_entry.startswith("/")
        normalized = path_entry[1:] if is_absolute else path_entry

        if not normalized:
            return "/"
        if normalized == partition:
            return f"/{partition}" if is_absolute else partition
        if not normalized.startswith(f"{partition}/"):
            return f"/{normalized}" if is_absolute else normalized

        rel_path = normalized[len(partition) + 1 :]
        resolved = self._resolve_partition_relpath(rel_path, partition_dir, partition)
        if resolved is None:
            return None

        canonical = f"{partition}/{resolved}" if resolved else partition
        return f"/{canonical}" if is_absolute else canonical

    def _resolve_partition_relpath(
        self, rel_path: str, partition_dir: str, partition: str
    ) -> str | None:
        if not rel_path:
            return ""

        candidate = rel_path
        prefix = f"{partition}/"
        while True:
            if os.path.lexists(os.path.join(partition_dir, candidate)):
                return candidate
            if os.path.lexists(os.path.join(partition_dir, partition, candidate)):
                return f"{partition}/{candidate}"
            if not candidate.startswith(prefix):
                return None
            candidate = candidate[len(prefix) :]

    def _is_file_context_pattern(self, path_entry: str) -> bool:
        return any(
            token in path_entry
            for token in ("(", ")", "[", "]", "?", "*", "|", "^", "$")
        )

    def _escape_file_context_path(self, path_entry: str) -> str:
        # Escape regex-meaningful characters that can appear in Android paths.
        # Stock Samsung contexts only escape . and +, but [ ] also appear
        # in real binaries (e.g. /system/bin/[ — the test command).
        return re.sub(r"([\[\].+])", r"\\\1", path_entry)

    def _update_op_list(self) -> None:
        out_dir = self._config.get("out_dir", "OUT")
        device = self._config.get("device", "SM-A325F")

        op_list = os.path.join(out_dir, "ZIP_PACKAGE", "dynamic_partitions_op_list")

        super_size = None
        if self._config_loader:
            super_size = self._config_loader.get_device_setting(
                device, "stock_super_size"
            )

        if super_size and LumiUtils.check_file(op_list):
            with open(op_list, "r") as f:
                content = f.read()
            content = re.sub(
                r"add_group samsung_dynamic_partitions .*",
                f"add_group samsung_dynamic_partitions {super_size}",
                content,
            )
            LumiUtils.replace_file(op_list, content)

        for partition_img in os.listdir(out_dir):
            if partition_img.endswith(".img"):
                partition = partition_img.replace(".img", "")
                size = os.path.getsize(os.path.join(out_dir, partition_img))
                if LumiUtils.check_file(op_list):
                    with open(op_list, "r") as f:
                        content = f.read()
                    content = re.sub(
                        rf"resize {partition} .*", f"resize {partition} {size}", content
                    )
                    LumiUtils.replace_file(op_list, content)

    def _update_metadata(self) -> None:
        device = self._config.get("device", "SM-A325F")
        firm_dir = self._config.get("firm_dir", "FIRMWARE")
        out_dir = self._config.get("out_dir", "OUT")
        version = self._config.get("version", "8.6.1")
        build_date = datetime.now().strftime("%d%m%Y")

        build_prop = os.path.join(firm_dir, "system", "system", "build.prop")
        fingerprint = "Unknown/Release-Keys"

        if LumiUtils.check_file(build_prop):
            with open(build_prop, "r") as f:
                for line in f:
                    if line.startswith("ro.system.build.fingerprint="):
                        fingerprint = line.split("=", 1)[1].strip()
                        break

        codename, display_name = DEVICE_CODENAMES.get(
            device, ("unknown", "Unknown Device")
        )

        updater_script = os.path.join(
            out_dir,
            "ZIP_PACKAGE",
            "META-INF",
            "com",
            "google",
            "android",
            "updater-script",
        )
        if LumiUtils.check_file(updater_script):
            with open(updater_script, "r") as f:
                content = f.read()

            content = re.sub(
                r'ui_print\("Source: .*"\);',
                f'ui_print("Source: {fingerprint}");',
                content,
            )
            content = re.sub(
                r'getprop\("ro\.boot\.em\.model"\).*',
                f'getprop("ro.boot.em.model") == "{device}" || '
                f'abort("E3004: This package is for {codename}");',
                content,
            )
            content = re.sub(
                r'ui_print\(".*for .*"\)',
                f'ui_print("   {version}-{build_date} UNOFFICIAL for {display_name}")',
                content,
            )

            LumiUtils.replace_file(updater_script, content)

        build_info = os.path.join(out_dir, "ZIP_PACKAGE", "build_info.txt")
        with open(build_info, "w") as f:
            f.write(f"device={codename}\n")
            f.write(f"version={version}-{build_date}\n")
            f.write(f"timestamp={int(datetime.now().timestamp())}\n")
            f.write("status=UNOFFICIAL\n")

    def _create_zip(self) -> None:
        out_dir = self._config.get("out_dir", "OUT")
        tmp_dir = self._config.get("tmp_dir", "TMP") or "/dev/shm/WORK"
        version = self._config.get("version", "8.6.1")
        build_date = datetime.now().strftime("%d%m%Y")
        device = self._config.get("device", "SM-A325F")
        zip_level = self._resolve_quality_setting(
            "zip_metadata_level", fallback=1, minimum=0, maximum=9
        )

        codename, _ = DEVICE_CODENAMES.get(device, ("unknown", "Unknown Device"))
        zip_file = os.path.join(
            out_dir, f"LumiROM_{version}-{build_date}_{codename}.zip"
        )
        zip_work = os.path.join(out_dir, "ZIP_PACKAGE")

        if LumiUtils.check_file(zip_file):
            LumiUtils.remove_path(zip_file)

        logger.info("  Creating flashable zip...")

        # 1. Add metadata/scripts and compressible partition artifacts with
        # light compression.
        files_to_zip = [
            os.path.join(zip_work, "META-INF"),
            os.path.join(zip_work, "build_info.txt"),
            os.path.join(zip_work, "dynamic_partitions_op_list"),
        ]

        boot_img = os.path.join(zip_work, "boot.img")
        if LumiUtils.check_file(boot_img):
            files_to_zip.append(boot_img)

        # Add compressible partition artifacts (.map, .transfer.list, .patch.dat)
        for f in os.listdir(tmp_dir):
            if f.endswith((".map", ".transfer.list", ".patch.dat")):
                files_to_zip.append(os.path.join(tmp_dir, f))

        sz_tool = SevenZip(verbose=self._config.get("verbose", False))
        sz_tool.add(zip_file, files_to_zip, compression_level=zip_level)

        # 2. Add already compressed partition artifacts (.new.dat.br) with
        # store-only (-mx=0)
        partition_artifacts = []
        for f in os.listdir(tmp_dir):
            if f.endswith(".new.dat.br"):
                partition_artifacts.append(os.path.join(tmp_dir, f))

        if partition_artifacts:
            sz_tool.add(zip_file, partition_artifacts, compression_level=0)

        logger.info("  Created: %s", os.path.basename(zip_file))

        firm_dir = self._config.get("firm_dir", "FIRMWARE")
        required_files = [
            d
            for d in os.listdir(firm_dir)
            if os.path.isdir(os.path.join(firm_dir, d)) and d != "config"
        ]
        missing = []
        for p in required_files:
            img_file = os.path.join(out_dir, f"{p}.img")
            if not LumiUtils.check_file(img_file):
                missing.append(p)

        if missing:
            logger.warning(f"  Missing partition images: {', '.join(missing)}")

        zip_size = os.path.getsize(zip_file)
        zip_size_gb = zip_size / (1024 * 1024 * 1024)
        if zip_size_gb < 2.0:
            logger.warning(
                f"  ZIP size is {zip_size_gb:.2f}GB - less than 2GB, may be incomplete!"
            )

        stdout = sz_tool.list_contents(zip_file)
        if stdout:
            logger.info("  ZIP contents:")
            for line in stdout.splitlines():
                if line.startswith("Path = "):
                    path = line[7:]
                    if path and not path.startswith("ZIP_PACKAGE"):
                        logger.info(f"    {path}")

    def _resolve_package_workers(self) -> int:
        cpu_count = max(1, os.cpu_count() or 1)
        configured = self._get_performance_setting("package_jobs", fallback="auto")
        if configured.lower() != "auto":
            try:
                return max(1, int(configured))
            except ValueError:
                pass
        return max(1, min(4, cpu_count // 4 or 1))

    def _resolve_mkfs_workers(self) -> int:
        cpu_count = max(1, os.cpu_count() or 1)
        configured = self._get_performance_setting("mkfs_workers", fallback="auto")
        if configured.lower() != "auto":
            try:
                return max(1, min(24, int(configured)))
            except ValueError:
                pass

        package_workers = self._resolve_package_workers()
        return max(1, min(24, cpu_count // max(1, package_workers)))

    def _resolve_quality_setting(
        self, key: str, fallback: int, minimum: int, maximum: int
    ) -> int:
        configured = self._get_performance_setting(key, fallback=str(fallback))
        try:
            value = int(configured)
        except ValueError:
            value = fallback
        return max(minimum, min(maximum, value))

    def _get_performance_setting(self, key: str, fallback: str) -> str:
        if self._config_loader is None:
            return fallback
        value = self._config_loader.get_build_setting(
            "performance", key, fallback=fallback
        )
        return str(value).strip()

    def _can_use_fast_img2sdat(self, image_path: str) -> bool:
        if not LumiUtils.check_file(image_path):
            return False
        return os.path.getsize(image_path) % 4096 == 0

    def _write_full_transfer_list(
        self, partition: str, image_path: str, tmp_dir: str
    ) -> None:
        total_blocks = os.path.getsize(image_path) // 4096
        transfer_list = os.path.join(tmp_dir, f"{partition}.transfer.list")
        lines = [
            "4\n",
            f"{total_blocks}\n",
            "0\n",
            "0\n",
        ]
        for start in range(0, total_blocks, 1024):
            end = min(total_blocks, start + 1024)
            lines.append(f"new 2,{start},{end}\n")
        LumiUtils.replace_file_lines(transfer_list, lines)
