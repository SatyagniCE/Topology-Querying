from pathlib import Path

import pytest

from circuit_ingest.html_export import export_corpus
from tests.fixtures.canonical_record import sample_record


def test_export_corpus_creates_searchable_offline_graph(tmp_path: Path):
    source = tmp_path / "source" / "circuits"
    source.mkdir(parents=True)
    (source / "1.json").write_text(
        sample_record("analoggenie:1").model_dump_json(), encoding="utf-8"
    )

    target = tmp_path / "visualizations"
    assert export_corpus(source.parent, target) == 1

    page = (target / "analoggenie_1.html").read_text(encoding="utf-8")
    index = (target / "index.html").read_text(encoding="utf-8")
    assert "analoggenie:1" in index
    assert "analoggenie_1.html" in index
    assert "new vis.Network" in page
    assert "Q30" in page
    assert "substrate" in page
    assert "unused" in page
    assert "https://" not in page
    assert (target / "assets" / "vis-network.min.js").is_file()
    assert (target / "assets" / "LICENSE-vis-network-MIT.txt").is_file()


def test_export_corpus_requires_circuit_json(tmp_path: Path):
    with pytest.raises(ValueError, match="no circuit JSON"):
        export_corpus(tmp_path, tmp_path / "out")
