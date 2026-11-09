"""Build the STJ Track add-on (a Blender extension .zip) from this repository.

    python tools/blender/build_addon.py [out_dir]            (default: dist/)

Stages tools/blender/addon/ with the modules the add-on runs (stj_blender, stj_profile, stj_ground, stj_core,
ground_bake) in lib/, then lets Blender build and validate the extension (`blender --command extension build`).
Needs Blender 5.2 or later: set STJ_BLENDER to its path when it is not on the PATH.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = [ROOT / "tools" / "blender" / n for n in ("stj_blender.py", "stj_profile.py", "stj_ground.py")] + \
          [ROOT / "tools" / n for n in ("stj_core.py", "ground_bake.py")]


def find_blender():
    for cand in (os.environ.get("STJ_BLENDER"), shutil.which("blender"),
                 r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"):
        if cand and Path(cand).is_file():
            return cand
    raise SystemExit("build_addon: Blender not found (set STJ_BLENDER)")


def stage(dest):
    dest = Path(dest)
    shutil.copytree(ROOT / "tools" / "blender" / "addon", dest, dirs_exist_ok=True)
    (dest / "lib").mkdir(exist_ok=True)
    for m in MODULES:
        shutil.copy2(m, dest / "lib" / m.name)
    shutil.copy2(ROOT / "LICENSE", dest / "LICENSE")
    return dest


def build(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = stage(Path(tmp) / "stj_track")
        r = subprocess.run([find_blender(), "--command", "extension", "build", "--source-dir", str(src),
                            "--output-dir", str(out.resolve())], capture_output=True, text=True, timeout=300)
    print(r.stdout.strip())
    if r.returncode:
        raise SystemExit(r.stderr.strip() or "build_addon: the build failed")
    return sorted(out.glob("stj_track-*.zip"))[-1]


if __name__ == "__main__":
    print("built", build(sys.argv[1] if len(sys.argv) > 1 else ROOT / "dist"))
