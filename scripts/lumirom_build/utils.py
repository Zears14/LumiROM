import hashlib
import logging
import os
import shutil
import stat
import subprocess
import tempfile
from typing import Iterable, Optional


class LumiUtils:
    @staticmethod
    def check_file(path: str) -> bool:
        """Check if a file or directory exists."""
        return os.path.exists(path)

    @staticmethod
    def is_official(build_signature: str, official_hash: str) -> str:
        current_signature = hashlib.sha256(build_signature.encode()).hexdigest()
        if current_signature == official_hash:
            return "OFFICIAL"
        return "UNOFFICIAL"

    @staticmethod
    def checkpoint_cil_hashes(
        firm_dir: str, logger_obj: logging.Logger
    ) -> list[tuple[str, str, int]]:
        """Log xxhash128 of CIL files to detect corruption or unintended changes."""
        cil_files: list[tuple[str, str, int]] = []
        for root, _, files in os.walk(firm_dir):
            for f in files:
                if f.endswith(".cil"):
                    full = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(full)
                        h = LumiUtils.xxh128_file(full)
                        rel = os.path.relpath(full, firm_dir)
                        cil_files.append((rel, h, sz))
                    except Exception:
                        pass
        cil_files.sort()
        for rel, h, sz in cil_files:
            logger_obj.debug("    %s  %s  (%d bytes)", h, rel, sz)
        return cil_files

    @staticmethod
    def make_executable(path: str) -> bool:
        """Ensure the target path is executable."""
        if not LumiUtils.check_file(path):
            return False
        subprocess.run(["chmod", "+x", path], check=False)
        return True

    @staticmethod
    def hex_patch(file_path: str, from_hex: str, to_hex: str) -> bool:
        if not LumiUtils.check_file(file_path):
            return False

        from_bytes = bytes.fromhex(from_hex)
        to_bytes = bytes.fromhex(to_hex)

        if len(from_bytes) != len(to_bytes):
            return False

        with open(file_path, "rb+") as f:
            data = f.read()
            if from_bytes not in data:
                return False

            new_data = data.replace(from_bytes, to_bytes, 1)
            f.seek(0)
            f.write(new_data)
            f.truncate()
            return True

    @staticmethod
    def remove_path(path: str) -> None:
        if not os.path.lexists(path):
            return
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
            return
        shutil.rmtree(path)

    @staticmethod
    def remove_targets(
        base_dir: str, targets: Iterable[str], logger_obj: logging.Logger
    ) -> int:
        removed = 0
        for target in targets:
            path = os.path.join(base_dir, target)
            if LumiUtils.check_file(path):
                LumiUtils.remove_path(path)
                logger_obj.info("  Removed: %s", target)
                removed += 1
        return removed

    @staticmethod
    def replace_file(path: str, content: str) -> None:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, dir=directory, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        os.replace(tmp_path, path)

    @staticmethod
    def replace_file_lines(path: str, lines: Iterable[str]) -> None:
        LumiUtils.replace_file(path, "".join(lines))

    @staticmethod
    def merge_tree(src: str, dst: str) -> None:
        os.makedirs(dst, exist_ok=True)
        shutil.copytree(
            src,
            dst,
            dirs_exist_ok=True,
            symlinks=True,
            copy_function=shutil.copy2,
        )

    @staticmethod
    def sort_unique_file(path: str) -> None:
        if not LumiUtils.check_file(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            lines = sorted(dict.fromkeys(f.readlines()))
        LumiUtils.replace_file_lines(path, lines)

    @staticmethod
    def _safe_mode(mode: int, is_dir: bool) -> int:
        normalized = mode | stat.S_IRUSR | stat.S_IWUSR
        if is_dir:
            normalized |= stat.S_IXUSR
        elif mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            normalized |= stat.S_IXUSR
        return stat.S_IMODE(normalized)

    @staticmethod
    def normalize_tree_permissions(root: str) -> None:
        if not LumiUtils.check_file(root):
            return

        for dirpath, dirnames, filenames in os.walk(root):
            LumiUtils.normalize_path_permissions(dirpath, is_dir=True)
            for name in dirnames:
                LumiUtils.normalize_path_permissions(
                    os.path.join(dirpath, name), is_dir=True
                )
            for name in filenames:
                LumiUtils.normalize_path_permissions(
                    os.path.join(dirpath, name), is_dir=False
                )

    @staticmethod
    def normalize_path_permissions(path: str, is_dir: Optional[bool] = None) -> None:
        if os.path.islink(path):
            return

        if is_dir is None:
            is_dir = os.path.isdir(path)

        current_mode = os.stat(path).st_mode
        os.chmod(path, LumiUtils._safe_mode(current_mode, is_dir))

    @staticmethod
    def stream_command(
        args: list[str],
        logger_obj: logging.Logger,
        cwd: Optional[str] = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        process = subprocess.Popen(
            args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        stdout_lines = []
        for line_bytes in iter(process.stdout.readline, b""):
            parts = line_bytes.split(b"\r")
            clean_line = parts[-1].decode("utf-8", "replace").strip()
            if not clean_line and len(parts) > 1:
                clean_line = parts[-2].decode("utf-8", "replace").strip()
            if clean_line:
                logger_obj.debug("  %s", clean_line)
                stdout_lines.append(clean_line)

        process.wait()
        if check and process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode, args, "\n".join(stdout_lines)
            )
        return subprocess.CompletedProcess(
            args, process.returncode, "\n".join(stdout_lines), ""
        )

    @staticmethod
    def run_or_stream(
        args: list[str],
        logger_obj: logging.Logger,
        stream: bool = False,
        cwd: Optional[str] = None,
        check: bool = False,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess:
        if not stream:
            return subprocess.run(
                args,
                cwd=cwd,
                check=check,
                capture_output=capture_output,
                text=True if capture_output else False,
            )
        return LumiUtils.stream_command(args, logger_obj, cwd=cwd, check=check)

    @staticmethod
    def xxh128_file(file_path: str) -> str:
        xxhsum = shutil.which("xxhsum")
        if xxhsum:
            result = subprocess.run(
                [xxhsum, "-H2", file_path],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split()[0].lower()

        try:
            import xxhash
        except ImportError as exc:
            raise RuntimeError(
                "Unable to calculate XXH128 firmware hash: install xxhsum "
                "or the Python xxhash module."
            ) from exc

        digest = xxhash.xxh3_128()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().lower()
