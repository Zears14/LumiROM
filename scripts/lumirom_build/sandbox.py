import hashlib
import json
import logging
import os
import shlex
import shutil
import sys
from typing import Iterable, List

from .config_loader import ConfigLoader
from .utils import LumiUtils

logger = logging.getLogger(__name__)


class PodmanSandbox:
    INSIDE_ENV = "LUMIROM_IN_SANDBOX"

    def __init__(self, config_loader: ConfigLoader, ws_root: str):
        self._config_loader = config_loader
        self._ws_root = os.path.abspath(ws_root)

    @classmethod
    def inside_sandbox(cls) -> bool:
        return os.environ.get(cls.INSIDE_ENV) == "1"

    def enabled(self) -> bool:
        return self._config_loader.get_build_setting_bool(
            "sandbox", "enabled", fallback=True
        )

    def should_wrap(self) -> bool:
        return self.enabled() and not self.inside_sandbox()

    def ensure_available(self) -> None:
        if shutil.which("podman") is None:
            raise RuntimeError(
                "Podman is required for sandboxed builds. "
                "Install podman or use --no-sandbox."
            )

    def image_name(self) -> str:
        base_name = self._config_loader.get_build_setting(
            "sandbox", "image_name", fallback="lumirom-build-sandbox"
        )
        base_image = self._config_loader.get_build_setting(
            "sandbox",
            "base_image",
            fallback="docker.io/library/alpine:3.20",
        )
        containerfile = self.containerfile_path()
        containerfile_bytes = b""
        if LumiUtils.check_file(containerfile):
            with open(containerfile, "rb") as f:
                containerfile_bytes = f.read()
        packages = ",".join(self.packages())
        digest = hashlib.sha256(
            "\n".join([base_image, packages]).encode("utf-8") + containerfile_bytes
        ).hexdigest()[:12]
        return f"{base_name}:{digest}"

    def containerfile_path(self) -> str:
        configured = self._config_loader.get_build_setting(
            "sandbox",
            "containerfile",
            fallback="containers/podman/Containerfile",
        )
        return os.path.join(self._ws_root, configured)

    def packages(self) -> List[str]:
        packages = self._config_loader.get_build_setting_list(
            "sandbox", "packages", fallback=[]
        )
        return list(packages)

    def _base_run_command(self, interactive: bool = False) -> list[str]:
        mount_path = self._config_loader.get_build_setting(
            "sandbox", "workspace_mount", fallback="/workspace"
        )
        privileged = self._config_loader.get_build_setting_bool(
            "sandbox", "privileged", fallback=False
        )
        shm_size = self._config_loader.get_build_setting(
            "sandbox", "shm_size", fallback="8g"
        )

        cmd = [
            "podman",
            "run",
            "--rm",
            "--userns=keep-id",
            "--security-opt",
            "label=disable",
            "-w",
            mount_path,
            "-v",
            f"{self._ws_root}:{mount_path}",
            "-e",
            "HOME=/tmp/lumirom-home",
        ]

        if privileged:
            cmd.append("--privileged")
        if shm_size:
            cmd.extend(["--shm-size", shm_size])
        if interactive and sys.stdin.isatty() and sys.stdout.isatty():
            cmd.extend(["-it"])

        return cmd

    def ensure_image(self) -> str:
        self.ensure_available()

        image_name = self.image_name()
        exists = LumiUtils.run_or_stream(
            ["podman", "image", "exists", image_name],
            logger,
            check=False,
        )
        if exists.returncode == 0:
            return image_name

        containerfile = self.containerfile_path()
        if not LumiUtils.check_file(containerfile):
            raise RuntimeError(f"Sandbox Containerfile not found: {containerfile}")

        base_image = self._config_loader.get_build_setting(
            "sandbox",
            "base_image",
            fallback="docker.io/library/alpine:3.20",
        )
        packages = " ".join(self.packages())

        build_cmd = [
            "podman",
            "build",
            "--pull=missing",
            "-t",
            image_name,
            "-f",
            containerfile,
            "--build-arg",
            f"BASE_IMAGE={base_image}",
            "--build-arg",
            f"SYSTEM_PACKAGES={packages}",
            self._ws_root,
        ]
        result = LumiUtils.run_or_stream(build_cmd, logger, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to build sandbox image {image_name}")
        return image_name

    def run(self, args: Iterable[str]) -> int:
        image_name = self.ensure_image()
        cmd = self._base_run_command(interactive=True)
        cmd.extend(["-e", f"{self.INSIDE_ENV}=1"])

        passthrough_env = [
            "CI",
            "COLORTERM",
            "FORCE_COLOR",
            "GITHUB_ACTIONS",
            "GITHUB_ENV",
            "GITHUB_REF",
            "GITHUB_RUN_ID",
            "GITHUB_SHA",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "LUMIROM_BUILD",
            "NO_PROXY",
            "OFFICIAL_HASH",
            "TERM",
            "TZ",
        ]
        for name in passthrough_env:
            value = os.environ.get(name)
            if value:
                cmd.extend(["-e", f"{name}={value}"])

        inner_args = list(args)
        if "--no-sandbox" not in inner_args:
            inner_args.append("--no-sandbox")

        cmd.extend(
            [
                image_name,
                "python3",
                "make",
                *inner_args,
            ]
        )
        return LumiUtils.run_or_stream(
            cmd, logger, check=False, capture_output=False
        ).returncode

    def probe_environment(
        self,
        required_bins: Iterable[str],
        required_paths: Iterable[str],
        min_tmpfs_free_gb: int,
        min_workspace_free_gb: int,
    ) -> None:
        image_name = self.ensure_image()
        mount_path = self._config_loader.get_build_setting(
            "sandbox", "workspace_mount", fallback="/workspace"
        )
        probe_script = """
import json
import os
import shutil
import subprocess
import sys
import tempfile

required_bins = json.loads(sys.argv[1])
required_paths = json.loads(sys.argv[2])
mount_path = sys.argv[3]
min_tmpfs_free_gb = int(sys.argv[4])
min_workspace_free_gb = int(sys.argv[5])

missing_bins = [name for name in required_bins if shutil.which(name) is None]
if missing_bins:
    raise SystemExit("Missing sandbox dependencies: " + ", ".join(missing_bins))

missing_paths = [
    path for path in required_paths
    if not os.path.exists(os.path.join(mount_path, path))
]
if missing_paths:
    raise SystemExit(
        "Missing mounted project files in sandbox: " + ", ".join(missing_paths)
    )

for path in (mount_path, os.path.join(mount_path, "logs"), "/dev/shm"):
    os.makedirs(path, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".lumirom-preflight-", dir=path, delete=True
    ) as tmp:
        tmp.write(b"ok")
        tmp.flush()

def free_gb(path: str) -> float:
    usage = shutil.disk_usage(path)
    return usage.free / (1024 ** 3)

workspace_free = free_gb(mount_path)
if workspace_free < min_workspace_free_gb:
    raise SystemExit(
        f"Sandbox workspace free space too low: {workspace_free:.1f} GiB "
        f"< {min_workspace_free_gb} GiB"
    )

tmpfs_free = free_gb("/dev/shm")
if tmpfs_free < min_tmpfs_free_gb:
    raise SystemExit(
        f"Sandbox shared memory too small: {tmpfs_free:.1f} GiB "
        f"< {min_tmpfs_free_gb} GiB"
    )

smoke_tests = [
    (["java", "-version"], {0}),
    (["7z", "i"], {0}),
    (["brotli", "--version"], {0}),
    (["simg2img"], {0, 1}),
]
for cmd, ok_returncodes in smoke_tests:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode not in ok_returncodes:
        output = (result.stderr or result.stdout).strip().splitlines()
        detail = output[0] if output else f"exit {result.returncode}"
        raise SystemExit(
            f"Sandbox tool smoke test failed for {' '.join(cmd)}: {detail}"
        )
"""
        cmd = self._base_run_command(interactive=False)
        cmd.extend(
            [
                image_name,
                "python3",
                "-c",
                probe_script,
                json.dumps(list(required_bins)),
                json.dumps(list(required_paths)),
                mount_path,
                str(min_tmpfs_free_gb),
                str(min_workspace_free_gb),
            ]
        )
        result = LumiUtils.run_or_stream(cmd, logger, check=False)
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip() or (
                f"Podman sandbox probe failed with exit code {result.returncode}"
            )
            raise RuntimeError(message)

    def privileged_cleanup(self, paths: Iterable[str]) -> bool:
        existing = [os.path.abspath(path) for path in paths if os.path.lexists(path)]
        if not existing:
            return True

        self.ensure_available()
        base_image = self._config_loader.get_build_setting(
            "sandbox",
            "base_image",
            fallback="docker.io/library/alpine:3.20",
        )

        cmd = [
            "podman",
            "run",
            "--rm",
            "--privileged",
            "--user",
            "root",
            "--security-opt",
            "label=disable",
        ]

        mount_targets = {}
        cleanup_targets = []
        for index, path in enumerate(existing):
            parent = os.path.dirname(path) or "/"
            mount_target = mount_targets.get(parent)
            if mount_target is None:
                mount_target = f"/cleanup/{index}"
                mount_targets[parent] = mount_target
                cmd.extend(["-v", f"{parent}:{mount_target}"])
            cleanup_targets.append(os.path.join(mount_target, os.path.basename(path)))

        cleanup_script = " && ".join(
            f"rm -rf -- {shlex.quote(target)}" for target in cleanup_targets
        )
        cmd.extend([base_image, "sh", "-lc", cleanup_script])
        return LumiUtils.run_or_stream(cmd, logger, check=False).returncode == 0
