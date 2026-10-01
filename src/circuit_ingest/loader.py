"""Discover official primary circuit bundles without following symbolic links."""
from pathlib import Path
from .models import SourceBundle


def discover(root: Path) -> list[SourceBundle]:
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"inaccessible dataset root: {root}")
    bundles = []
    for directory in sorted(root.iterdir(), key=lambda path: (not path.name.isdecimal(), int(path.name) if path.name.isdecimal() else 0)):
        if not directory.name.isdecimal() or not directory.is_dir() or directory.is_symlink():
            continue
        circuit_id = directory.name
        primary = directory / f"{circuit_id}.cir"
        port = directory / f"Port{circuit_id}.txt"
        auxiliary = sorted((path for path in directory.iterdir() if path not in (primary, port)), key=lambda path: path.name)
        bundles.append(SourceBundle(dataset_name="AnalogGenie", circuit_id=circuit_id, root_directory=root,
                                    primary_netlist_path=primary, port_path=port, auxiliary_paths=auxiliary))
    return bundles
