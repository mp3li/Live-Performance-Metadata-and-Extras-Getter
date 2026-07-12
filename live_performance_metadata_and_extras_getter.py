#!/usr/bin/env python3
"""Launcher for Live Performance Metadata and Extras Getter by mp3li."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


BASE_SCRIPT_PATH = (
    Path(__file__).resolve().parent
    / "Base Script"
    / "live_performance_metadata_and_extras_getter_base.py"
)


def load_main():
    spec = importlib.util.spec_from_file_location(
        "live_performance_metadata_and_extras_getter_base",
        BASE_SCRIPT_PATH,
    )
    if not spec or not spec.loader:
        raise ImportError(f"Could not load base script: {BASE_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main


if __name__ == "__main__":
    raise SystemExit(load_main()())
