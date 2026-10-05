"""
OmniBioAI backend.src.control_center.core.settings.

Purpose:
    Defines Settings and load_settings for backend.src.control_center.core.settings.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    services: dict[str, dict[str, Any]]
    system: dict[str, Any]


def _default_config_path() -> str:
    return os.environ.get("CONTROL_CENTER_CONFIG", "/config/control_center.yaml")


def load_settings() -> Settings:
    path = _default_config_path()
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Control Center config not found: {path}. "
            f"Mount it and/or set CONTROL_CENTER_CONFIG."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    services = raw.get("services", {}) or {}
    system = raw.get("system", {}) or {}

    return Settings(services=services, system=system)
