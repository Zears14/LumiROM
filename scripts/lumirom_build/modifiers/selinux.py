import glob
import os
import re
import sys
from typing import List

from ..exceptions import BuildError
from ..patchers.text_patcher import TextPatcher
from ..tools.secilc import Secilc
from ..utils import LumiUtils
from .base_modifier import BaseModifier

if os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")) not in sys.path:
    sys.path.insert(
        0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    )
from sexpdata.sexpdata import Symbol, dumps, parse

from .constants import UNSUPPORTED_SELINUX


class SelinuxFixerModifier(BaseModifier):
    def apply(self) -> None:
        self._fix_selinux(self.firm_dir)

    def _fix_selinux(self, firm_dir: str) -> None:
        system_ext_dir = self._resolve_system_ext_dir(firm_dir)
        system_dir = os.path.join(firm_dir, "system", "system")
        if not system_ext_dir:
            self.logger.warning(
                "  system_ext SELinux directory not found, skipping SELinux fixes"
            )
            return

        mapped_files = []
        sepolicy_files = []

        for base_dir in [system_dir, system_ext_dir]:
            selinux_dir = os.path.join(base_dir, "etc", "selinux")
            if LumiUtils.check_file(selinux_dir):
                mapping_dir = os.path.join(selinux_dir, "mapping")
                if LumiUtils.check_file(mapping_dir):
                    mapped_files.extend(glob.glob(os.path.join(mapping_dir, "*.cil")))
                sepolicy_name = (
                    "system_ext_sepolicy.cil"
                    if "system_ext" in base_dir
                    else "plat_sepolicy.cil"
                )
                sepolicy = os.path.join(selinux_dir, sepolicy_name)
                if LumiUtils.check_file(sepolicy):
                    sepolicy_files.append(sepolicy)

        import glob as _glob

        for base_dir in [system_dir, system_ext_dir]:
            compat_pattern = os.path.join(
                base_dir, "etc", "selinux", "mapping", "*.compat.cil"
            )
            for compat_file in _glob.glob(compat_pattern):
                removed = TextPatcher.delete_lines_matching(
                    compat_file, r"^\(typeattribute sysfs_boot_info\)$", use_regex=True
                )
                if removed:
                    self.logger.info(
                        "  Removed conflicting sysfs_boot_info from %s",
                        os.path.basename(compat_file),
                    )

        for sepolicy_cil in sepolicy_files:
            if "system_ext" in sepolicy_cil:
                removed = TextPatcher.delete_lines_matching(
                    sepolicy_cil,
                    r"/sys/kernel/firmware_config|/sys/vm/compaction_proactiveness",
                    use_regex=True,
                )
                if removed:
                    self.logger.info(
                        "  Removed %d unsupported SELinux policy entries", removed
                    )

        declared_types = self._get_declared_cil_types(firm_dir)
        unsupported = set(UNSUPPORTED_SELINUX)

        for cil_path in mapped_files + sepolicy_files:
            if not os.path.exists(cil_path):
                continue
            try:
                with open(cil_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if (
                            "typeattributeset " in line
                            or "expandtypeattribute " in line
                        ):
                            words = line.replace("(", " ").replace(")", " ").split()
                            if len(words) > 1:
                                for w in words[1:]:
                                    if w in ("true", "false", "object_r", "s0"):
                                        continue
                                    if w not in declared_types:
                                        unsupported.add(w)
            except Exception as e:
                self.logger.warning(
                    "  Error searching for undeclared types in "
                    f"{os.path.basename(cil_path)}: {e}"
                )

        for cil_path in mapped_files + sepolicy_files:
            if not os.path.exists(cil_path):
                continue
            scrubbed = self._scrub_sepolicy_types(cil_path, list(unsupported))
            if scrubbed:
                self.logger.info(
                    "  Structurally SCRUBbed %d entries from %s (%s)",
                    scrubbed,
                    os.path.basename(cil_path),
                    os.path.basename(os.path.dirname(os.path.dirname(cil_path))),
                )

        selinux_dir = os.path.join(system_ext_dir, "etc", "selinux")
        prop_context = os.path.join(selinux_dir, "system_ext_property_contexts")
        if LumiUtils.check_file(prop_context):
            removed = TextPatcher.delete_lines_matching(
                prop_context,
                r"^init\.svc\.vendor\.wvkprov_server_hal\s+u:object_r:wvkprov_prop:s0$",
                use_regex=True,
            )
            if removed:
                self.logger.info(
                    "  Removed %d unsupported SELinux property entries", removed
                )

        self._fix_unmapped_property_contexts(firm_dir, selinux_dir)
        self._verify_all_cil_files(firm_dir)

    def _resolve_system_ext_dir(self, firm_dir: str) -> str | None:
        candidates = [
            os.path.join(firm_dir, "system", "system_ext"),
            os.path.join(firm_dir, "system", "system", "system_ext"),
            os.path.join(firm_dir, "system_ext"),
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        return None

    def _scrub_sepolicy_types(self, sepolicy_path: str, unsupported_types: list) -> int:
        if not LumiUtils.check_file(sepolicy_path):
            return 0

        with open(sepolicy_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        type_set = set(unsupported_types)
        new_lines: List[str] = []
        scrubbed = 0

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                new_lines.append(line)
                continue

            if stripped.startswith("(type ") or stripped.startswith("(typeattribute "):
                token = stripped.split()[1].rstrip(")")
                if token in type_set:
                    scrubbed += 1
                    continue

            if not any(t in stripped for t in type_set):
                new_lines.append(line)
                continue

            try:
                parsed = parse(stripped)
            except Exception:
                new_lines.append(line)
                continue

            if not parsed:
                continue

            cleaned = []
            for stmt in parsed:
                if not isinstance(stmt, list) or not stmt:
                    cleaned.append(stmt)
                    continue

                op = stmt[0].value() if isinstance(stmt[0], Symbol) else None

                if op == "typeattributeset":
                    c = self._clean_cil_expr(stmt, type_set)
                    if c is not None:
                        cleaned.append(c)
                else:
                    if not self._has_dropped_token(stmt, type_set):
                        cleaned.append(stmt)

            if not cleaned:
                scrubbed += 1
                continue

            cleaned_str = " ".join(dumps(x) for x in cleaned)
            if cleaned_str != stripped:
                scrubbed += 1
            new_lines.append(cleaned_str + "\n")

        LumiUtils.replace_file(sepolicy_path, "".join(new_lines))
        return scrubbed

    def _has_dropped_token(self, expr, drop_tokens: set) -> bool:
        if isinstance(expr, Symbol):
            val = expr.value()
            if val in drop_tokens:
                return True
            base_val = re.sub(r"_\d+_\d+$", "", val)
            return base_val in drop_tokens
        if isinstance(expr, list):
            return any(self._has_dropped_token(x, drop_tokens) for x in expr)
        return False

    def _clean_cil_expr(self, expr, drop_tokens: set):
        if not isinstance(expr, list):
            if isinstance(expr, Symbol):
                val = expr.value()
                base_val = re.sub(r"_\d+_\d+$", "", val)
                if val in drop_tokens or base_val in drop_tokens:
                    return None
            return expr

        cleaned = []
        for item in expr:
            c = self._clean_cil_expr(item, drop_tokens)
            if c is not None:
                cleaned.append(c)

        if not cleaned:
            return None

        op = cleaned[0].value() if isinstance(cleaned[0], Symbol) else None

        if op in ("not",):
            if len(cleaned) == 1:
                return None
        if op in ("and", "or", "xor"):
            if len(cleaned) == 1:
                return None
            if len(cleaned) == 2:
                return cleaned[1]
        if op in ("typeattributeset", "expandtypeattribute", "typeattribute"):
            if len(cleaned) < 3 and op in ("typeattributeset", "expandtypeattribute"):
                return None
            if len(cleaned) < 2 and op == "typeattribute":
                return None

        return cleaned

    def _get_declared_cil_types(self, firm_dir: str) -> set:
        declared = {
            "and",
            "or",
            "not",
            "xor",
            "all",
            "none",
            "object_r",
            "s0",
            "tcontext",
            "scontext",
            "any",
            "true",
            "false",
            "r",
            "w",
            "x",
            "h1",
            "h2",
            "l1",
            "l2",
        }
        for root, _, files in os.walk(firm_dir):
            for file in files:
                if file.endswith(".cil"):
                    try:
                        with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                            for line in f:
                                if (
                                    line.startswith("(type ")
                                    or line.startswith("(typeattribute ")
                                    or line.startswith("(typealias ")
                                    or line.startswith("(macro ")
                                    or line.startswith("(role ")
                                ):
                                    parts = line.split()
                                    if len(parts) > 1:
                                        declared.add(parts[1].rstrip(")"))
                    except Exception:
                        pass
        return declared

    def _fix_unmapped_property_contexts(self, firm_dir: str, selinux_dir: str) -> None:
        cil_dirs = [
            os.path.join(firm_dir, "system", "system", "etc", "selinux"),
            selinux_dir,
        ]
        declared_types: set[str] = set()
        type_re = re.compile(r"^\(type\s+(\S+)\)")
        for cil_dir in cil_dirs:
            if not os.path.isdir(cil_dir):
                continue
            for root, _dirs, files in os.walk(cil_dir):
                for fname in files:
                    if not fname.endswith(".cil"):
                        continue
                    with open(os.path.join(root, fname), "r", encoding="utf-8") as f:
                        for line in f:
                            m = type_re.match(line)
                            if m:
                                declared_types.add(m.group(1))

        if not declared_types:
            return

        ctx_type_re = re.compile(r"u:object_r:([^:]+):s0")
        ctx_files = []
        for cil_dir in cil_dirs:
            if not os.path.isdir(cil_dir):
                continue
            for fname in os.listdir(cil_dir):
                if fname.endswith("property_contexts"):
                    ctx_files.append(os.path.join(cil_dir, fname))

        for ctx_path in ctx_files:
            if not LumiUtils.check_file(ctx_path):
                continue
            with open(ctx_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines: List[str] = []
            removed = 0
            for line in lines:
                m = ctx_type_re.search(line)
                if m and m.group(1) not in declared_types:
                    removed += 1
                    continue
                new_lines.append(line)

            if removed:
                LumiUtils.replace_file(ctx_path, "".join(new_lines))
                self.logger.info(
                    "  Removed %d unmapped property entries from %s",
                    removed,
                    os.path.basename(ctx_path),
                )

    def _verify_all_cil_files(self, firm_dir: str) -> None:
        self.logger.info("  Validating compiled CIL policy tree...")

        stock_vndk_version = self._config.get("_stock_vndk_version", "30")

        all_cils: List[str] = []
        for root, _, files in os.walk(firm_dir):
            for f in files:
                if f.endswith(".cil"):
                    all_cils.append(os.path.join(root, f))

        if not all_cils:
            self.logger.warning("  No CIL files found for validation!")
            return

        def _priority(path: str) -> tuple:
            rel = os.path.relpath(path, firm_dir)
            if "plat_sepolicy.cil" in rel and "system/system/" in rel:
                return (0, rel)
            if "plat_sepolicy_genfs" in rel:
                return (1, rel)
            if "system/system/" in rel and "/mapping/" in rel:
                return (2, rel)
            if "system_ext_sepolicy.cil" in rel:
                return (3, rel)
            if "system_ext/" in rel and "/mapping/" in rel:
                return (4, rel)
            if "product_sepolicy.cil" in rel:
                return (5, rel)
            if ("product/" in rel) and "/mapping/" in rel:
                return (6, rel)
            if "plat_pub_versioned.cil" in rel:
                return (7, rel)
            if "vendor_sepolicy.cil" in rel:
                return (8, rel)
            if "odm/" in rel:
                return (9, rel)
            return (10, rel)

        cil_files = sorted(all_cils, key=_priority)

        secilc_tool = Secilc(verbose=self._config.get("verbose", False))
        success = secilc_tool.compile(cil_files, stock_vndk_version)

        if not success:
            raise BuildError("CIL validation failed.")

        self.logger.info("    CIL validation passed.")


class CilHashesCheckpointerModifier(BaseModifier):
    def __init__(self, config: dict, config_loader=None, label: str = "PRE-PACKAGING"):
        super().__init__(config, config_loader)
        self.label = label

    def apply(self) -> None:
        if not self._config.get("verbose", False):
            return
        self.logger.debug("  [CIL-CHECKPOINT:%s]", self.label)
        LumiUtils.checkpoint_cil_hashes(self.firm_dir, self.logger)
