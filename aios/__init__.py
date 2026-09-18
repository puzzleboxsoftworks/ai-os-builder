"""ai-os-builder: describe an OS in English, get a bootable Linux ISO."""

from .builder import Builder, BuildError, run_iso
from .planner import plan, plan_offline
from .spec import OSSpec, SpecError

__all__ = ["Builder", "BuildError", "OSSpec", "SpecError", "plan", "plan_offline", "run_iso"]
__version__ = "0.1.0"
