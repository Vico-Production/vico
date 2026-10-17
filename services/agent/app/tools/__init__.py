from __future__ import annotations

from app.tools import apps, browser, control, desktop, files, research, system
from app.tools.base import ToolRegistry


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for module in (files, apps, browser, desktop, control, research, system):
        for spec in module.specs():
            registry.register(spec)
    return registry
