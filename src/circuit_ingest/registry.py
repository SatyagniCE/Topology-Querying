"""Observed AnalogGenie device spellings and ordered contacts."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DeviceSpec:
    canonical_type: str
    category: Literal["transistor", "passive", "macro"]
    terminals: tuple[str, ...]


DEVICE_SPECS = {
    "nmos4": DeviceSpec("nmos", "transistor", ("drain", "gate", "source", "bulk")),
    "pmos4": DeviceSpec("pmos", "transistor", ("drain", "gate", "source", "bulk")),
    "npn": DeviceSpec("npn", "transistor", ("collector", "base", "emitter", "substrate")),
    "pnp": DeviceSpec("pnp", "transistor", ("collector", "base", "emitter", "substrate")),
    "resistor": DeviceSpec("resistor", "passive", ("p", "n")),
    "capacitor": DeviceSpec("capacitor", "passive", ("p", "n")),
    "inductor": DeviceSpec("inductor", "passive", ("p", "n")),
    "diode": DeviceSpec("diode", "passive", ("p", "n")),
    "XOR": DeviceSpec("xor", "macro", ("a", "b", "vdd", "vss", "y")),
    "PFD": DeviceSpec("pfd", "macro", ("a", "b", "qa", "qb", "vdd", "vss")),
    "INVERTER": DeviceSpec("inverter", "macro", ("a", "q", "vdd", "vss")),
    "TRANSMISSION_GATE": DeviceSpec("transmission_gate", "macro", ("a", "b", "control", "vdd", "vss")),
}
