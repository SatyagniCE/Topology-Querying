"""Netlist device spellings and their device-graph representations.

Each netlist instance becomes one graph node. Its ordered terminals determine
which terminal labels appear on edges to other devices sharing a net.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class DeviceType:
    graph_kind: str
    terminal_roles: tuple[str, ...]
    tunable_attributes: Mapping[str, str]


_MOS_TERMINALS = ("drain", "gate", "source", "body")
_PAIR_TERMINALS = ("positive", "negative")
_DIODE_TERMINALS = ("anode", "cathode")
# AnalogGenie's SPICE2GRAPH_full.py labels the first three BJT contacts C/B/E.
# Its converter omits contact four; "substrate" follows SPICE convention, and
# every BJT instance in the corpus connects that contact to 0.
_BJT_TERMINALS = ("collector", "base", "emitter", "substrate")
_NMOS = DeviceType("nmos", _MOS_TERMINALS, MappingProxyType({"w": "mos_width"}))
_PMOS = DeviceType("pmos", _MOS_TERMINALS, MappingProxyType({"w": "mos_width"}))

DEVICE_TYPES: Mapping[str, DeviceType] = MappingProxyType(
    {
        "nmos": _NMOS,
        "nmos4": _NMOS,
        "pmos": _PMOS,
        "pmos4": _PMOS,
        "npn": DeviceType("npn", _BJT_TERMINALS, MappingProxyType({})),
        "pnp": DeviceType("pnp", _BJT_TERMINALS, MappingProxyType({})),
        "diode": DeviceType("diode", _DIODE_TERMINALS, MappingProxyType({})),
        "resistor": DeviceType(
            "resistor", _PAIR_TERMINALS, MappingProxyType({"r": "resistance"})
        ),
        "capacitor": DeviceType(
            "capacitor", _PAIR_TERMINALS, MappingProxyType({"c": "capacitance"})
        ),
        "inductor": DeviceType(
            "inductor", _PAIR_TERMINALS, MappingProxyType({"l": "inductance"})
        ),
        "vsource": DeviceType(
            "voltage_source", _PAIR_TERMINALS, MappingProxyType({"dc": "voltage"})
        ),
        "isource": DeviceType(
            "current_source", _PAIR_TERMINALS, MappingProxyType({"dc": "current"})
        ),
        "port": DeviceType("port", ("port", "reference"), MappingProxyType({})),
        "balun": DeviceType(
            "balun",
            ("single_ended", "differential_positive", "differential_negative"),
            MappingProxyType({}),
        ),
    }
)
