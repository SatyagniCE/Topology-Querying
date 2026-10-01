"""AnalogGenie source adapter and canonical ingestion model."""
from .models import CircuitRecord, DetectionResult, ParseIssue, ParseMode, ParseResult, SourceBundle
from .loader import discover
from .parser import AnalogGenieParser

__all__ = ["AnalogGenieParser", "CircuitRecord", "DetectionResult", "ParseIssue", "ParseMode", "ParseResult", "SourceBundle", "discover"]
