import os
from typing import Callable, Dict, List, Optional, Tuple

from ..utils import LumiUtils
from .base_modifier import BaseModifier


class FstabModifierBase(BaseModifier):
    def _iter_fstab_paths(self) -> List[str]:
        vendor_etc = os.path.join(self.firm_dir, "vendor", "etc")
        if not os.path.isdir(vendor_etc):
            return []
        return [
            os.path.join(vendor_etc, name)
            for name in sorted(os.listdir(vendor_etc))
            if name.startswith("fstab.mt")
        ]

    def _rewrite_fstab_file(
        self, fstab_path: str, line_rewriter: Callable[[str], Tuple[str, bool]]
    ) -> int:
        if not os.path.exists(fstab_path):
            return 0
        with open(fstab_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        rewritten_lines: List[str] = []
        changes = 0
        for line in lines:
            new_line, changed = line_rewriter(line)
            rewritten_lines.append(new_line)
            changes += int(changed)
        if changes:
            LumiUtils.replace_file_lines(fstab_path, rewritten_lines)
        return changes

    def _split_fstab_line(self, line: str) -> Optional[Tuple[List[str], str]]:
        newline = "\n" if line.endswith("\n") else ""
        stripped = line.rstrip("\n")
        if not stripped or stripped.lstrip().startswith("#"):
            return None
        parts = stripped.split(None, 4)
        if len(parts) != 5:
            return None
        return parts, newline


class DisableFbeModifier(FstabModifierBase):
    def apply(self) -> None:
        self.logger.info("Disabling FBE...")
        for fstab_path in self._iter_fstab_paths():
            changes = self._rewrite_fstab_file(fstab_path, self._rewrite_fbe_flags_line)
            if changes:
                self.logger.info(
                    "  Rewrote %d /data FBE entries in %s",
                    changes,
                    os.path.basename(fstab_path),
                )

    def _rewrite_fbe_flags_line(self, line: str) -> Tuple[str, bool]:
        parsed = self._split_fstab_line(line)
        if not parsed:
            return line, False
        parts, newline = parsed
        if parts[1] != "/data":
            return line, False
        flags = parts[4].split(",")
        new_flags: List[str] = []
        changed = False
        encryptable_seen = False
        for flag in flags:
            if flag.startswith("fileencryption=") or flag.startswith("forceencrypt="):
                changed = True
                if not encryptable_seen:
                    new_flags.append("encryptable")
                    encryptable_seen = True
                continue
            if flag == "encryptable":
                if encryptable_seen:
                    changed = True
                    continue
                encryptable_seen = True
            new_flags.append(flag)
        if not changed:
            return line, False
        parts[4] = ",".join(new_flags)
        return "\t".join(parts) + newline, True


class PatchFstabErofsModifier(FstabModifierBase):
    def apply(self) -> None:
        self.logger.info("Patching fstab for EROFS...")
        mount_map = {
            "/system": "erofs",
            "/vendor": "erofs",
            "/product": "erofs",
            "/odm": "erofs",
        }
        for fstab_path in self._iter_fstab_paths():
            changes = self._rewrite_fstab_file(
                fstab_path, lambda line: self._rewrite_erofs_mount_line(line, mount_map)
            )
            if changes:
                self.logger.info(
                    "  Rewrote %d mount entries to EROFS in %s",
                    changes,
                    os.path.basename(fstab_path),
                )

    def _rewrite_erofs_mount_line(
        self, line: str, mount_map: Dict[str, str]
    ) -> Tuple[str, bool]:
        parsed = self._split_fstab_line(line)
        if not parsed:
            return line, False
        parts, newline = parsed
        target_fs = mount_map.get(parts[1])
        if not target_fs or parts[2] == target_fs:
            return line, False
        parts[2] = target_fs
        return "\t".join(parts) + newline, True
