"""Install a pinned Mihomo binary, verifying its archive SHA256."""

import gzip
import hashlib
import io
import platform
import subprocess
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v1.19.33"
ARCHIVES = {
    "Linux": (
        f"mihomo-linux-amd64-compatible-{VERSION}.gz",
        "386508bfb1c72c43b6a0eda73708ecdce82546581b0ebcb16366c53757c622b6",
    ),
    "Windows": (
        f"mihomo-windows-amd64-compatible-{VERSION}.zip",
        "7aaf636a4f2172dcd8ec34ac4f52797b059195e5afd6409508c963e545f8864d",
    ),
}


def install() -> Path:
    system = platform.system()
    if system not in ARCHIVES or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("Auto-install supports Windows/Linux x64; use build.py --mihomo PATH otherwise")
    target = ROOT / ".tools" / VERSION / ("mihomo.exe" if system == "Windows" else "mihomo")
    if target.is_file():
        return target
    name, expected = ARCHIVES[system]
    url = f"https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{name}"
    print(f"Downloading Mihomo {VERSION}: {name}", flush=True)
    with urlopen(Request(url, headers={"User-Agent": "ruleset-hub"}), timeout=120) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError(f"Mihomo archive checksum mismatch: {name}")
    if system == "Windows":
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            executables = [item for item in zipped.namelist() if item.endswith(".exe")]
            if len(executables) != 1:
                raise ValueError("Expected one executable in Mihomo archive")
            binary = zipped.read(executables[0])
    else:
        binary = gzip.decompress(archive)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(binary)
    target.chmod(0o755)
    return target


if __name__ == "__main__":
    subprocess.run([str(install()), "-v"], check=True)
