"""Public-repository secret scan.

Prefers `git ls-files` so the scan follows `.gitignore` exactly. When git is unavailable or
refuses the working tree (a fresh clone with different ownership, a container without git), it
falls back to a filesystem walk with an explicit exclusion list and says so, because silently
scanning nothing would be worse than scanning approximately.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[oprsu]_[A-Za-z0-9_]{30,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "generic bearer": re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._~-]{20,}"),
    "SSH host entry": re.compile(r"(?m)^\s*(?:HostName|IdentityFile)\s+\S+"),
}
URI_CREDENTIAL = re.compile(
    r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)"
    r"(?:\+[a-z0-9]+)?://[^\s:/]+:([^@\s/]+)@[^\s]+"
)
PUBLIC_FIXTURE_PASSWORDS = {
    "CHANGE_ME",
    "REPLACE_FOR_LOCAL_DEVELOPMENT_ONLY",
    "local_development_only",
    "test_only_not_a_secret",
    "super_secret_pw",  # literal in tests/unit/test_error_redaction.py, never a real credential
}
WALK_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    "build",
    "dist",
    "node_modules",
    ".idea",
    ".vscode",
}


def _git_files(root: Path) -> list[Path] | None:
    command = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return [root / line for line in result.stdout.splitlines() if line]


def _walked_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in WALK_EXCLUDED_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        found.append(path)
    return found


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    files = _git_files(root)
    if files is None:
        print("git file listing unavailable; scanning the working tree directly.")
        files = _walked_files(root)
    findings: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(root)
        if relative == Path("scripts/secret_scan.py"):
            continue  # this file holds the detection patterns themselves
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative}: {label}")
        for match in URI_CREDENTIAL.finditer(text):
            if match.group(1) not in PUBLIC_FIXTURE_PASSWORDS and "..." not in match.group(1):
                findings.append(f"{relative}: database URL with embedded credential")
    if findings:
        print("Potential secrets found:")
        print("\n".join(sorted(set(findings))))
        return 1
    print(f"Public-repository secret scan passed over {len(files)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
