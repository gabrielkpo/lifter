"""Entry point of the API on Vercel (project lifter-api), found by Vercel's FastAPI detection.

The package lives in src/ (src layout), which Vercel does not search: put it on the path, then
expose the app built from the environment (lifter.api.hosted).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lifter.api.vercel import app  # noqa: E402

__all__ = ["app"]
