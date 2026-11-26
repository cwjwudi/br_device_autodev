"""B&R PLC automation toolchain."""

from .backends.pvi import PviSessionManager, PviTarget, VariableRef, parse_variable_ref
from .client import PviClient
from .project import inspect_project
from .services import PviTraceError, RuntimePviService, TraceManager

__version__ = "0.17.0a1"

__all__ = [
    "__version__",
    "PviClient",
    "RuntimePviService",
    "TraceManager",
    "PviTraceError",
    "PviSessionManager",
    "PviTarget",
    "VariableRef",
    "parse_variable_ref",
    "inspect_project",
]
