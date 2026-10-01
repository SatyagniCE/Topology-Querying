"""Common contract for source-specific topology parsers."""
from typing import Protocol
from .models import DetectionResult, ParseMode, ParseResult, SourceBundle


class CircuitParser(Protocol):
    dialect: str

    def can_parse(self, source: SourceBundle) -> DetectionResult: ...

    def parse(self, source: SourceBundle, *, mode: ParseMode = ParseMode.STRICT) -> ParseResult: ...
