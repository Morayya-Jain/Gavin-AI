"""
Core business logic package for BrainDock.

Contains the headless SessionEngine (extracted from gui/app.py)
and platform permission checks. Zero UI dependencies.
"""

from core.engine import SessionEngine

__all__ = ["SessionEngine"]
