#!/usr/bin/env python3
"""Old name of tools/stj_validate.py, kept so that documented commands and imports keep working.

New code uses `stj_validate`: another project's top-level `validate` module (SVJ ships one) cannot then take its place.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stj_validate  # noqa: E402

# the same names under the old module name, also for a caller that loaded this file by its path
globals().update({k: v for k, v in vars(stj_validate).items() if not k.startswith("__")})

if __name__ == "__main__":
    sys.exit(stj_validate.main(sys.argv[1:]))
