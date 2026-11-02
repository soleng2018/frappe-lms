"""Healthy when a process whose command line contains every argument given is running."""

import glob
import sys
from pathlib import Path


def healthy(want, proc="/proc"):
    for path in glob.glob(f"{proc}/[0-9]*/cmdline"):
        try:
            parts = Path(path).read_bytes().decode(errors="replace").split("\0")
        except OSError:
            continue
        if "frappe.utils.bench_helper" in " ".join(parts) and all(
            w in parts for w in want
        ):
            return True
    return False


if __name__ == "__main__":
    sys.exit(0 if healthy(sys.argv[1:]) else 1)
