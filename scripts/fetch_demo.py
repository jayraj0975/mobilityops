"""Download the demo bundle, verify its SHA-256 and unpack it. Standard library only.

    python scripts/fetch_demo.py URL SHA256 [DEST]

Refuses archive members that would land outside DEST.
"""

from __future__ import annotations

import hashlib
import sys
import tarfile
import urllib.request
from pathlib import Path


def main(url: str, sha256: str, dest: str = ".") -> None:
    if not url.startswith("https://"):
        raise SystemExit("the demo URL must be https")
    req = urllib.request.Request(url, headers={"User-Agent": "mobilityops-fetch-demo"})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (https enforced above)
        blob = r.read(200 * 1024 * 1024)
    got = hashlib.sha256(blob).hexdigest()
    if got != sha256.lower():
        raise SystemExit(f"checksum mismatch: expected {sha256}, got {got}")
    root = Path(dest).resolve()
    tmp = root / ".demo.tar.gz"
    tmp.write_bytes(blob)
    with tarfile.open(tmp) as tar:
        for m in tar.getmembers():
            target = (root / m.name).resolve()
            if not target.is_relative_to(root) or not (m.isfile() or m.isdir()):
                raise SystemExit(f"unsafe archive member: {m.name}")
        tar.extractall(root, filter="data")
    tmp.unlink()
    print(f"unpacked {len(blob):,} bytes into {root}")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
