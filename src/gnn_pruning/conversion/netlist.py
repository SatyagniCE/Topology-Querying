"""Strict parser for the checked-in analog circuit netlist sources.

The parser deliberately retains source expressions rather than interpreting their
arithmetic.  It only resolves a standalone engineering literal or a standalone
symbol supplied by the caller as a fixed value.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import re

from gnn_pruning.conversion.device_types import DEVICE_TYPES

_ATTRIBUTE_START = re.compile(r"(?<!\S)([A-Za-z_][A-Za-z0-9_]*)=")
_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ENGINEERING_LITERAL = re.compile(
    r"(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?P<suffix>MEG|[TGMKmunpf])?\Z",
    re.IGNORECASE,
)
_ENGINEERING_MULTIPLIERS = {
    "": 1.0,
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}


class NetlistParseError(ValueError):
    """A source-located failure while parsing a netlist statement."""

    def __init__(self, path: str, line_number: int, text: str, reason: str) -> None:
        self.path = path
        self.line_number = line_number
        self.text = text
        self.reason = reason
        super().__init__(f"{path}:{line_number}: {reason}: {text}")


@dataclass(frozen=True)
class ParsedExpression:
    """An attribute expression and the narrow resolution safe at parse time."""

    raw: str
    value: float | None
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class ParsedInstance:
    """A typed netlist instance with terminal order and source context intact."""

    instance_id: str
    kind: str
    nets: tuple[str, ...]
    terminal_roles: tuple[str, ...]
    attributes: Mapping[str, str]
    expressions: Mapping[str, ParsedExpression]
    line_number: int
    source_text: str
    raw_instance_id: str | None = None


@dataclass(frozen=True)
class ParsedNetlist:
    """The structural source input for a circuit, with its canonical text hash."""

    instances: tuple[ParsedInstance, ...]
    source_sha256: str


@dataclass(frozen=True)
class _Subcircuit:
    pins: tuple[str, ...]
    statements: tuple[tuple[int, str], ...]
    path: str
    line_number: int

    @property
    def signature(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return self.pins, tuple(statement for _, statement in self.statements)


class SubcircuitRegistry:
    """Index corpus definitions while resolving each call in its file context."""

    def __init__(self, corpus_root: Path) -> None:
        self.by_path: dict[str, dict[str, _Subcircuit]] = {}
        self.by_name: dict[str, list[_Subcircuit]] = {}
        for source in sorted(corpus_root.rglob("*.cir")):
            path = str(source.resolve())
            definitions, _ = _split_definitions(
                source.read_text(encoding="utf-8"), path
            )
            self.by_path[path] = definitions
            for name, definition in definitions.items():
                self.by_name.setdefault(name, []).append(definition)

    def resolve(
        self, name: str, from_path: str, line_number: int, statement: str
    ) -> _Subcircuit | None:
        source = Path(from_path).resolve()
        own = self.by_path.get(str(source), {}).get(name)
        if own is not None:
            return own
        sibling = source.with_name(source.stem + "_full.cir")
        nearby = self.by_path.get(str(sibling), {}).get(name)
        if nearby is not None:
            return nearby
        candidates = self.by_name.get(name, [])
        if not candidates:
            return None
        if len({candidate.signature for candidate in candidates}) != 1:
            locations = ", ".join(
                f"{candidate.path}:{candidate.line_number}"
                for candidate in candidates
            )
            raise NetlistParseError(
                from_path,
                line_number,
                statement,
                f"ambiguous subckt {name}; definitions: {locations}",
            )
        return candidates[0]


@lru_cache(maxsize=8)
def _cached_registry(corpus_root: Path) -> SubcircuitRegistry:
    return SubcircuitRegistry(corpus_root)


def _registry_for_path(path: str) -> SubcircuitRegistry | None:
    source = Path(path)
    if not source.is_file() or source.suffix.lower() != ".cir":
        return None
    for parent in source.resolve().parents:
        if parent.name == "Dataset":
            return _cached_registry(parent)
    return None


def parse_netlist(
    text: str,
    fixed_values: Mapping[str, float],
    *,
    path: str = "<in-memory netlist>",
) -> ParsedNetlist:
    """Parse supported source statements without evaluating arbitrary expressions.

    ``fixed_values`` is only used for a complete, bare attribute symbol.  Compound
    expressions are carried forward unchanged for parameter materialization.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized_fixed = _normalize_fixed_values(fixed_values, path)
    definitions, top_level = _split_definitions(text, path)
    registry = _registry_for_path(path)

    instances: list[ParsedInstance] = []
    seen_ids: set[str] = set()

    def expand(
        statements: tuple[tuple[int, str], ...] | list[tuple[int, str]],
        prefix: str,
        pins: Mapping[str, str],
        stack: tuple[str, ...],
        source_path: str,
    ) -> None:
        names = Counter(
            statement.split("(", 1)[0].strip()
            for _, statement in statements
            if "(" in statement
        )
        for line_number, statement in statements:
            kind = _statement_kind(statement)
            definition = None
            if kind not in DEVICE_TYPES and kind is not None:
                if source_path == path:
                    definition = definitions.get(kind)
                if definition is None and registry is not None:
                    definition = registry.resolve(
                        kind, source_path, line_number, statement
                    )
            if definition is not None:
                assert kind is not None
                # Phase 1 graphs contain primitive devices only: expand each
                # call here. The path survives in instance IDs, but the named
                # functional block is not a graph node or learned feature.
                call_id, call_nets = _parse_subcircuit_call(
                    statement, source_path, line_number, kind
                )
                scoped_call_id = (
                    f"{call_id}@L{line_number}" if names[call_id] > 1 else call_id
                )
                if len(call_nets) != len(definition.pins):
                    raise NetlistParseError(
                        source_path, line_number, statement,
                        f"expected {len(definition.pins)} terminals for {kind}, got {len(call_nets)}",
                    )
                if kind in stack:
                    raise NetlistParseError(
                        source_path, line_number, statement, "recursive subckt"
                    )
                mapped = tuple(_scope_net(net, pins, prefix) for net in call_nets)
                expand(
                    definition.statements,
                    prefix + scoped_call_id + "/",
                    dict(zip(definition.pins, mapped, strict=True)),
                    stack + (kind,),
                    definition.path,
                )
                continue
            instance = _parse_statement(
                statement, normalized_fixed, source_path, line_number
            )
            local_id = (
                f"{instance.instance_id}@L{line_number}"
                if names[instance.instance_id] > 1
                else instance.instance_id
            )
            instance = replace(
                instance,
                instance_id=prefix + local_id,
                nets=tuple(_scope_net(net, pins, prefix) for net in instance.nets),
            )
            if instance.instance_id in seen_ids:
                raise NetlistParseError(
                    source_path, line_number, statement,
                    f"duplicate instance ID {instance.instance_id}",
                )
            seen_ids.add(instance.instance_id)
            instances.append(instance)

    expand(top_level, "", {}, (), path)
    return ParsedNetlist(
        instances=tuple(instances),
        source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _split_definitions(
    text: str, path: str
) -> tuple[dict[str, _Subcircuit], list[tuple[int, str]]]:
    definitions: dict[str, _Subcircuit] = {}
    top_level: list[tuple[int, str]] = []
    active_name: str | None = None
    active_line = 0
    active_pins: tuple[str, ...] = ()
    active_body: list[tuple[int, str]] = []
    for line_number, statement in _logical_statements(text, path):
        fields = statement.split()
        directive = fields[0].lower()
        if directive == "subckt":
            if active_name is not None or len(fields) < 3:
                raise NetlistParseError(path, line_number, statement, "invalid subckt definition")
            active_name, *pins = fields[1:]
            if active_name in definitions or len(set(pins)) != len(pins):
                raise NetlistParseError(path, line_number, statement, "duplicate subckt or pin")
            active_line = line_number
            active_pins = tuple(pins)
            active_body = []
        elif directive == "ends":
            if active_name is None or len(fields) != 2 or fields[1] != active_name:
                raise NetlistParseError(path, line_number, statement, "mismatched ends")
            definitions[active_name] = _Subcircuit(
                active_pins, tuple(active_body), path, active_line
            )
            active_name = None
        elif active_name is not None:
            active_body.append((line_number, statement))
        else:
            top_level.append((line_number, statement))
    if active_name is not None:
        raise NetlistParseError(path, 0, active_name, "unterminated subckt")
    return definitions, top_level


def _statement_kind(statement: str) -> str | None:
    closing = statement.find(")")
    if closing < 0:
        return None
    fields = statement[closing + 1 :].split(None, 1)
    return fields[0] if fields else None


def _parse_subcircuit_call(
    statement: str, path: str, line_number: int, kind: str
) -> tuple[str, tuple[str, ...]]:
    matched = re.fullmatch(r"([^\s()]+)\s*\(([^()]*)\)\s+(\S+)", statement)
    if matched is None or matched.group(3) != kind:
        raise NetlistParseError(path, line_number, statement, "malformed subckt instance")
    return matched.group(1), tuple(
        _unescape_net(net, path, line_number, statement)
        for net in matched.group(2).split()
    )


def _scope_net(net: str, pins: Mapping[str, str], prefix: str) -> str:
    if net in pins:
        return pins[net]
    if not prefix or net in {"0", "GND", "VDD"}:
        return net
    return prefix + net


def parse_engineering_literal(value: object) -> float:
    """Return a finite SI float for a numeric or supported engineering literal."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric literal")
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        matched = _ENGINEERING_LITERAL.fullmatch(value.strip())
        if matched is None:
            raise ValueError(f"invalid engineering literal {value!r}")
        suffix = (matched.group("suffix") or "").lower()
        result = float(matched.group("number")) * _ENGINEERING_MULTIPLIERS[suffix]
    else:
        raise ValueError("value must be numeric or an engineering literal string")
    if not math.isfinite(result):
        raise ValueError("numeric literal must be finite")
    return result


def _normalize_fixed_values(
    fixed_values: Mapping[str, float], path: str
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for symbol, value in fixed_values.items():
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            raise NetlistParseError(
                path, 0, "", "fixed symbol names must be identifiers"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise NetlistParseError(
                path, 0, "", f"fixed value for {symbol} must be numeric"
            )
        numeric = float(value)
        if not math.isfinite(numeric):
            raise NetlistParseError(
                path, 0, "", f"fixed value for {symbol} must be finite"
            )
        normalized[symbol] = numeric
    return normalized


def _logical_statements(text: str, path: str):
    parts: list[str] = []
    first_line = 0
    for line_number, physical_line in enumerate(text.splitlines(), start=1):
        stripped = physical_line.strip()
        if not stripped or stripped.startswith("//"):
            if parts:
                raise NetlistParseError(
                    path,
                    first_line,
                    " ".join(parts),
                    "continuation must be followed by a statement line",
                )
            continue
        if parts and stripped.startswith("+"):
            stripped = stripped[1:].lstrip()
        continued = stripped.endswith("\\")
        if continued:
            stripped = stripped[:-1].rstrip()
            if not stripped:
                raise NetlistParseError(
                    path, line_number, physical_line, "empty continuation"
                )
        if not parts:
            first_line = line_number
        parts.append(stripped)
        if continued:
            continue
        yield first_line, " ".join(parts)
        parts = []
    if parts:
        raise NetlistParseError(
            path, first_line, " ".join(parts), "unterminated continuation"
        )


def _parse_statement(
    statement: str, fixed_values: Mapping[str, float], path: str, line_number: int
) -> ParsedInstance:
    opening = statement.find("(")
    closing = statement.find(")", opening + 1) if opening >= 0 else -1
    if opening < 0 or closing < 0:
        raise NetlistParseError(path, line_number, statement, "malformed terminal list")
    if opening == 0 or not statement[:opening].strip():
        raise NetlistParseError(path, line_number, statement, "missing instance ID")
    instance_id = statement[:opening].strip()
    if any(character.isspace() for character in instance_id):
        raise NetlistParseError(path, line_number, statement, "malformed instance ID")
    net_text = statement[opening + 1 : closing].strip()
    if "(" in net_text or ")" in net_text:
        raise NetlistParseError(path, line_number, statement, "malformed terminal list")
    if not net_text:
        raise NetlistParseError(path, line_number, statement, "missing terminals")
    after_terminals = statement[closing + 1 :].strip()
    if not after_terminals:
        raise NetlistParseError(path, line_number, statement, "missing device kind")
    fields = after_terminals.split(None, 1)
    kind = fields[0]
    device_type = DEVICE_TYPES.get(kind)
    if device_type is None:
        raise NetlistParseError(
            path, line_number, statement, f"unknown device kind {kind}"
        )
    terminal_roles = device_type.terminal_roles
    nets = tuple(
        _unescape_net(net, path, line_number, statement) for net in net_text.split()
    )
    if len(nets) != len(terminal_roles):
        raise NetlistParseError(
            path,
            line_number,
            statement,
            f"expected {len(terminal_roles)} terminals for {kind}, got {len(nets)}",
        )
    attributes = _parse_attributes(
        fields[1] if len(fields) == 2 else "",
        fixed_values,
        path,
        line_number,
        statement,
    )
    return ParsedInstance(
        instance_id=instance_id,
        kind=kind,
        nets=nets,
        terminal_roles=terminal_roles,
        attributes={name: expression.raw for name, expression in attributes.items()},
        expressions=attributes,
        line_number=line_number,
        source_text=statement,
        raw_instance_id=instance_id,
    )


def _unescape_net(net: str, path: str, line_number: int, statement: str) -> str:
    result = net.replace("\\+", "+").replace("\\-", "-")
    if "\\" in result:
        raise NetlistParseError(
            path, line_number, statement, f"unsupported net escape {net}"
        )
    return result


def _parse_attributes(
    text: str,
    fixed_values: Mapping[str, float],
    path: str,
    line_number: int,
    statement: str,
) -> dict[str, ParsedExpression]:
    if not text:
        return {}
    matches = list(_ATTRIBUTE_START.finditer(text))
    if not matches or text[: matches[0].start()].strip():
        raise NetlistParseError(path, line_number, statement, "malformed attributes")
    result: dict[str, ParsedExpression] = {}
    for index, matched in enumerate(matches):
        name = matched.group(1)
        value_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(text)
        )
        raw = text[matched.end() : value_end].strip()
        if not raw:
            raise NetlistParseError(
                path, line_number, statement, f"missing value for {name}"
            )
        if raw.count("(") != raw.count(")"):
            raise NetlistParseError(
                path, line_number, statement, "unbalanced parentheses"
            )
        if name in result:
            raise NetlistParseError(
                path, line_number, statement, f"duplicate attribute {name}"
            )
        try:
            result[name] = _parse_expression(raw, fixed_values)
        except ValueError as error:
            raise NetlistParseError(path, line_number, statement, str(error)) from error
    return result


def _parse_expression(raw: str, fixed_values: Mapping[str, float]) -> ParsedExpression:
    value: float | None
    if _ENGINEERING_LITERAL.fullmatch(raw):
        value = parse_engineering_literal(raw)
    else:
        value = fixed_values.get(raw)
    return ParsedExpression(
        raw=raw,
        value=value,
        symbols=tuple(dict.fromkeys(_SYMBOL.findall(raw))),
    )
