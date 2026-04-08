import mmap
import os
import re
from typing import Optional, Pattern


class TextPatcher:
    @staticmethod
    def _get_compiled_pattern(pattern: str, use_regex: bool) -> Pattern:
        if use_regex:
            return re.compile(pattern)
        return re.compile(re.escape(pattern))

    @staticmethod
    def replace_line(file_path: str, old_line: str, new_line: str) -> bool:
        if not os.path.exists(file_path):
            return False

        with open(file_path, "r+") as f:
            # Use mmap for in-memory file editing
            mm = mmap.mmap(f.fileno(), 0)
            content = mm.read().decode("utf-8")
            mm.close()

        if old_line not in content:
            return False

        new_content = content.replace(old_line, new_line)

        with open(file_path, "w") as f:
            f.write(new_content)
        return True

    @staticmethod
    def replace_pattern(
        file_path: str, pattern: str, replacement: str, use_regex: bool = False
    ) -> int:
        if not os.path.exists(file_path):
            return 0

        with open(file_path, "r") as f:
            content = f.read()

        compiled = TextPatcher._get_compiled_pattern(pattern, use_regex)
        new_content, count = compiled.subn(replacement, content)

        if count > 0:
            with open(file_path, "w") as f:
                f.write(new_content)

        return count

    @staticmethod
    def delete_lines_matching(
        file_path: str, pattern: str, use_regex: bool = False
    ) -> int:
        if not os.path.exists(file_path):
            return 0

        compiled = TextPatcher._get_compiled_pattern(pattern, use_regex)

        with open(file_path, "r") as f:
            lines = f.readlines()

        new_lines = [line for line in lines if not compiled.search(line)]
        deleted = len(lines) - len(new_lines)

        if deleted > 0:
            with open(file_path, "w") as f:
                f.writelines(new_lines)

        return deleted

    @staticmethod
    def append_line(
        file_path: str, new_line: str, after_pattern: Optional[str] = None
    ) -> bool:
        with open(file_path, "r+") as f:
            lines = f.readlines()

        if after_pattern:
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if after_pattern in line:
                    new_lines.append(new_line + "\n")
            with open(file_path, "w") as f:
                f.writelines(new_lines)
            return True
        else:
            with open(file_path, "a") as f:
                f.write(new_line + "\n")
            return True
