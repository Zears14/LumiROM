import logging
import os
import shutil
import tempfile

from .config_loader import ConfigLoader
from .exceptions import ConfigurationError, DependencyError
from .utils import LumiUtils

logger = logging.getLogger(__name__)


class PreflightChecker:
    _SMOKE_TESTS = {
        "7z": (["7z", "i"], {0}),
        "aria2c": (["aria2c", "--version"], {0}),
        "brotli": (["brotli", "--version"], {0}),
        "debugfs": (["debugfs", "-V"], {0}),
        "file": (["file", "--version"], {0}),
        "java": (["java", "-version"], {0}),
        "python3": (["python3", "--version"], {0}),
        "simg2img": (["simg2img"], {0, 1}),
        "unzip": (["unzip", "-v"], {0}),
        "xxd": (["xxd", "-v"], {0}),
        "xxhsum": (["xxhsum", "-V"], {0}),
        "zstd": (["zstd", "--version"], {0}),
    }

    def __init__(self, config_loader: ConfigLoader):
        self._config_loader = config_loader
        self._log = logger

    def check_dependencies(self) -> None:
        required_bins = self._config_loader.get_build_setting_list(
            "dependencies", "required_bins", fallback=""
        )
        if not required_bins:
            required_bins = [
                "7z",
                "java",
                "python3",
                "simg2img",
                "aria2c",
                "brotli",
                "debugfs",
                "tar",
                "file",
                "unzip",
                "xxd",
                "xxhsum",
                "zstd",
            ]

        missing = [b for b in required_bins if not shutil.which(b)]
        if missing:
            raise DependencyError(f"Missing system dependencies: {', '.join(missing)}")

        unusable = []
        for binary in required_bins:
            self._log.debug("Checking dependency: %s", binary)
            smoke = self._SMOKE_TESTS.get(binary)
            if smoke is None:
                continue

            cmd, ok_returncodes = smoke
            result = LumiUtils.run_or_stream(cmd, self._log, check=False)
            if result.returncode not in ok_returncodes:
                summary = (result.stderr or result.stdout).strip().splitlines()
                detail = summary[0] if summary else f"exit {result.returncode}"
                unusable.append(f"{binary} ({detail})")

        if unusable:
            raise DependencyError(
                "Installed dependencies failed a basic smoke test: "
                + ", ".join(unusable)
            )

    def check_project_files(self, ws_root: str) -> None:
        required_paths = [
            os.path.join(ws_root, "bin/apktool/apktool.jar"),
            os.path.join(ws_root, "bin/erofs-utils/extract.erofs"),
            os.path.join(ws_root, "bin/erofs-utils/mkfs.erofs"),
            os.path.join(ws_root, "bin/img2sdat/img2sdat"),
            os.path.join(ws_root, "bin/py_scripts/imgextractor.py"),
            os.path.join(
                ws_root,
                "template/META-INF/com/google/android/update-binary",
            ),
            os.path.join(
                ws_root,
                "template/META-INF/com/google/android/updater-script",
            ),
        ]
        missing = [p for p in required_paths if not LumiUtils.check_file(p)]
        if missing:
            raise ConfigurationError(f"Missing project files: {', '.join(missing)}")

    def check_project_tooling(self, ws_root: str) -> None:
        tool_checks = [
            (
                "apktool",
                [
                    "java",
                    "-jar",
                    os.path.join(ws_root, "bin/apktool/apktool.jar"),
                    "--version",
                ],
                {0},
            ),
            (
                "extract.erofs",
                [os.path.join(ws_root, "bin/erofs-utils/extract.erofs"), "--version"],
                {0, 2},
            ),
            (
                "mkfs.erofs",
                [os.path.join(ws_root, "bin/erofs-utils/mkfs.erofs"), "--version"],
                {0},
            ),
            (
                "img2sdat",
                ["python3", os.path.join(ws_root, "bin/img2sdat/img2sdat"), "-h"],
                {0},
            ),
        ]
        failed = []
        for label, cmd, ok_returncodes in tool_checks:
            result = LumiUtils.run_or_stream(cmd, self._log, check=False)
            if result.returncode not in ok_returncodes:
                summary = (result.stderr or result.stdout).strip().splitlines()
                detail = summary[0] if summary else f"exit {result.returncode}"
                failed.append(f"{label} ({detail})")

        if failed:
            raise ConfigurationError(
                "Project tooling failed a basic smoke test: " + ", ".join(failed)
            )

    def ensure_permissions(self, ws_root: str) -> None:
        executables = [
            os.path.join(ws_root, "make"),
            os.path.join(ws_root, "bin/erofs-utils/extract.erofs"),
            os.path.join(ws_root, "bin/erofs-utils/mkfs.erofs"),
            os.path.join(ws_root, "bin/img2sdat/img2sdat"),
        ]
        for exe in executables:
            LumiUtils.make_executable(exe)

    def check_device_config(self, device: str) -> None:
        has_ini = (
            self._config_loader.get_device_setting(device, "stock_vndk_version")
            is not None
        )
        if not has_ini:
            raise ConfigurationError(
                f"Device config not found for {device}. "
                f"Create config/devices/{device}.ini"
            )

    def check_local_environment(self, ws_root: str, cache_dir: str) -> None:
        self.ensure_permissions(ws_root)
        self.check_dependencies()
        self.check_project_files(ws_root)
        self.check_project_tooling(ws_root)
        self.check_write_access(ws_root, cache_dir)
        self.check_system_resources(ws_root, cache_dir, include_tmpfs=True)

    def check_sandbox_host_environment(
        self, ws_root: str, cache_dir: str, sandbox
    ) -> None:
        self.check_project_files(ws_root)
        self.check_write_access(ws_root, cache_dir, include_tmpfs=False)
        self.check_system_resources(ws_root, cache_dir, include_tmpfs=False)
        sandbox.ensure_available()
        sandbox.probe_environment(
            required_bins=self._config_loader.get_build_setting_list(
                "dependencies", "required_bins", fallback=""
            ),
            required_paths=[
                "bin/apktool/apktool.jar",
                "bin/erofs-utils/extract.erofs",
                "bin/erofs-utils/mkfs.erofs",
                "bin/img2sdat/img2sdat",
                "bin/py_scripts/imgextractor.py",
            ],
            min_tmpfs_free_gb=self._config_loader.get_build_setting_int(
                "preflight", "min_tmpfs_free_gb", fallback=4
            ),
            min_workspace_free_gb=self._config_loader.get_build_setting_int(
                "preflight", "min_workspace_free_gb", fallback=16
            ),
        )

    def check_write_access(
        self, ws_root: str, cache_dir: str, include_tmpfs: bool = True
    ) -> None:
        logs_dir = os.path.join(ws_root, "logs")
        cache_parent = (
            cache_dir if os.path.isdir(cache_dir) else os.path.dirname(cache_dir)
        )
        probe_targets = [
            ("workspace", ws_root),
            ("logs", logs_dir),
            ("cache", cache_parent or ws_root),
        ]
        if include_tmpfs:
            tmpfs_parent = (
                os.path.dirname(
                    self._config_loader.get_build_setting(
                        "workspace", "tmpfs_work", fallback="/dev/shm/WORK"
                    )
                )
                or "/dev/shm"
            )
            probe_targets.append(("shared memory", tmpfs_parent))

        for label, path in probe_targets:
            self._probe_writable_path(label, path)

    def check_system_resources(
        self, ws_root: str, cache_dir: str, include_tmpfs: bool = True
    ) -> None:
        min_cpu_count = self._config_loader.get_build_setting_int(
            "preflight", "min_cpu_count", fallback=2
        )
        cpu_count = os.cpu_count() or 1
        if cpu_count < min_cpu_count:
            raise DependencyError(
                f"Insufficient CPU threads: found {cpu_count}, "
                f"need at least {min_cpu_count}"
            )

        min_memory_gb = self._config_loader.get_build_setting_int(
            "preflight", "min_memory_gb", fallback=8
        )
        mem_total_gb = self._read_memtotal_gb()
        if mem_total_gb < min_memory_gb:
            raise DependencyError(
                f"Insufficient system memory: found {mem_total_gb:.1f} GiB, "
                f"need at least {min_memory_gb} GiB"
            )

        self._check_disk_free(
            "workspace",
            ws_root,
            self._config_loader.get_build_setting_int(
                "preflight", "min_workspace_free_gb", fallback=16
            ),
        )
        self._check_disk_free(
            "cache",
            cache_dir,
            self._config_loader.get_build_setting_int(
                "preflight", "min_cache_free_gb", fallback=4
            ),
        )
        if include_tmpfs:
            self._check_disk_free(
                "shared memory",
                self._config_loader.get_build_setting(
                    "workspace", "tmpfs_work", fallback="/dev/shm/WORK"
                ),
                self._config_loader.get_build_setting_int(
                    "preflight", "min_tmpfs_free_gb", fallback=4
                ),
            )

        tmpfs_path = self._config_loader.get_build_setting(
            "workspace", "tmpfs_work", fallback="/dev/shm/WORK"
        )
        self._log.info(
            "Environment OK: cpu=%s mem=%.1fGiB workspace_free=%.1fGiB%s",
            cpu_count,
            mem_total_gb,
            self._disk_free_gb(ws_root),
            f" {os.path.basename(tmpfs_path)}: {self._disk_free_gb(tmpfs_path):.1f}GiB"
            if include_tmpfs
            else "",
        )

    @staticmethod
    def check_workspace_clean() -> None:
        from .exceptions import BuildError

        transient_dirs = ["FIRMWARE", "WORK", "OUT", "TMP", "/dev/shm/WORK"]
        dirty = [d for d in transient_dirs if LumiUtils.check_file(d)]
        if dirty:
            raise BuildError(
                f"Workspace is dirty. Found: {', '.join(dirty)}\n"
                "    Run './make clean' before starting a new build."
            )

    @staticmethod
    def check_repo_root() -> None:
        from .exceptions import BuildError

        if not os.path.isdir("scripts") or not os.path.isdir("scripts/lumirom_build"):
            raise BuildError("Must be run from the repository root.")

    def _probe_writable_path(self, label: str, path: str) -> None:
        os.makedirs(path, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".lumirom-preflight-",
                dir=path,
                delete=True,
            ) as tmp:
                tmp.write(b"ok")
                tmp.flush()
        except OSError as exc:
            self._log.exception("Filesystem probe failed for %s at %s", label, path)
            raise DependencyError(
                f"{label.capitalize()} path is not writable: {path} ({exc})"
            ) from exc

    def _check_disk_free(self, label: str, path: str, min_gb: int) -> None:
        if min_gb <= 0:
            return
        free_gb = self._disk_free_gb(path)
        if free_gb < min_gb:
            raise DependencyError(
                f"Insufficient {label} free space: found {free_gb:.1f} GiB at "
                f"{self._existing_path(path)}, need at least {min_gb} GiB"
            )

    def _disk_free_gb(self, path: str) -> float:
        target = self._existing_path(path)
        usage = shutil.disk_usage(target)
        return usage.free / (1024**3)

    def _existing_path(self, path: str) -> str:
        candidate = os.path.abspath(path)
        while not LumiUtils.check_file(candidate):
            parent = os.path.dirname(candidate)
            if parent == candidate:
                return os.getcwd()
            candidate = parent
        return candidate

    def _read_memtotal_gb(self) -> float:
        meminfo = "/proc/meminfo"
        if not LumiUtils.check_file(meminfo):
            return 0.0
        with open(meminfo, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) / (1024**2)
        return 0.0
