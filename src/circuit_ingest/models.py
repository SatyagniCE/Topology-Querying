"""Versioned, source-independent topology records for ingestion."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"
PARSER_VERSION = "1.0.0"


class ParseMode(str, Enum):
    STRICT = "strict"
    LENIENT = "lenient"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParseIssue(Record):
    severity: Literal["info", "warning", "error", "fatal"]
    code: str
    message: str
    source_file: str
    source_line: int | None = None
    context: dict[str, str | int] = Field(default_factory=dict)


class Connection(Record):
    terminal: str
    terminal_ordinal: int
    net_id: str


class DeviceRecord(Record):
    id: str
    ordinal: int
    source_instance: str
    source_line: int
    raw_type: str
    canonical_type: str
    category: Literal["transistor", "passive", "macro", "opaque"]
    connections: list[Connection]
    parameters: dict[str, str] = Field(default_factory=dict)
    raw_line: str


class NetRecord(Record):
    id: str
    name: str
    is_external: bool
    port_ordinal: int | None
    degree_by_terminal: int


class PortRecord(Record):
    name: str
    ordinal: int
    net_id: str
    role: str | None = None
    referenced_by_device: bool


class SourceRecord(Record):
    primary_netlist: str
    port_file: str
    primary_sha256: str
    port_sha256: str
    auxiliary_files: list[str]


class ParserRecord(Record):
    name: str = "analoggenie"
    version: str = PARSER_VERSION
    mode: ParseMode


class Statistics(Record):
    device_count: int
    net_count: int
    external_port_count: int
    connection_count: int
    device_type_counts: dict[str, int]
    duplicate_source_instance_count: int
    unreferenced_port_count: int
    unknown_device_type_count: int


class CircuitRecord(Record):
    schema_version: str = SCHEMA_VERSION
    parser: ParserRecord
    circuit_id: str
    source_circuit_id: str
    dataset: str
    source: SourceRecord
    ports: list[PortRecord]
    nets: list[NetRecord]
    devices: list[DeviceRecord]
    statistics: Statistics
    issues: list[ParseIssue]


class ParseResult(Record):
    status: Literal["valid", "valid_with_warnings", "quarantined", "failed"]
    circuit: CircuitRecord | None
    issues: list[ParseIssue]


class SourceBundle(Record):
    dataset_name: str
    circuit_id: str
    root_directory: Path
    primary_netlist_path: Path
    port_path: Path
    auxiliary_paths: list[Path]


class DetectionResult(Record):
    supported: bool
    reason: str
