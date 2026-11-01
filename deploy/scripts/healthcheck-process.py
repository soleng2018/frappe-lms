"""Healthy when a process whose command line contains every argument given is running."""
import glob
import sys
from pathlib import Path

want = sys.argv[1:]
for path in glob.glob("/proc/[0-9]*/cmdline"):
    try:
        parts = Path(path).read_bytes().decode(errors="replace").split("\0")
    except OSError:
        continue
    if "frappe.utils.bench_helper" in " ".join(parts) and all(w in parts for w in want):
        sys.exit(0)
sys.exit(1)
