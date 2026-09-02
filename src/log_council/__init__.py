"""LogCouncil: evidence-first, multi-agent log analysis."""

from .orchestrator import CouncilOrchestrator
from .parser import parse_log_document, parse_log_file, parse_log_text

__all__ = [
    "CouncilOrchestrator",
    "parse_log_document",
    "parse_log_file",
    "parse_log_text",
]
__version__ = "0.1.0"
