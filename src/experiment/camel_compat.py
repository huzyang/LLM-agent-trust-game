"""Small compatibility helpers for the pinned CAMEL release."""

import os
import sys
from types import ModuleType


def prepare_camel_imports() -> None:
    """Skip an unused CAMEL toolkit that writes to ``/tmp`` on import.

    CAMEL 0.2.82 eagerly imports ``earth_science_toolkit``. That module
    creates ``/tmp/earth_science`` at import time, which resolves to a drive
    root on Windows and can fail before the experiment starts. This project
    does not use that toolkit, so provide the symbol CAMEL expects without
    importing the problematic optional module.
    """
    if os.name != "nt":
        return

    module_name = "camel.toolkits.earth_science_toolkit"
    if module_name in sys.modules:
        return

    compatibility_module = ModuleType(module_name)

    class EarthScienceToolkit:  # pragma: no cover - intentionally unused
        pass

    compatibility_module.EarthScienceToolkit = EarthScienceToolkit
    sys.modules[module_name] = compatibility_module
