from __future__ import annotations

import os
from pathlib import Path


def default_data_dir() -> Path:
    """Return the default BridgeCal data directory.

    Default: %APPDATA%\BridgeCal\ on Windows, otherwise ~/.bridgecal
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "BridgeCal"
    return Path.home() / ".bridgecal"
