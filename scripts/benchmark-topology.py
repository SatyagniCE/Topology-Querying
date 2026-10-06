"""Record candidate rankings and latency; not an electrical accuracy benchmark."""
import argparse
import json
from pathlib import Path
import time

import numpy as np

from circuit_workbench.catalog import Catalog
from circuit_workbench.retrieval import Retrieval, VERSION
from circuit_workbench.settings import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--stress", action="store_true", help="Verify large supported fanout has bounded profile latency")
    args = parser.parse_args()
    if args.stress:
        from circuit_workbench.topology import topology_profile
        from circuit_workbench.uploads import parse_upload
        text = "\n".join(f"M{i} (d{i} in 0 0) nmos4" for i in range(2000))
        record = parse_upload(text, "Maximum supported shared-gate fanout", "in 0")
        start = time.perf_counter()
        profile = topology_profile(record)
        elapsed = time.perf_counter() - start
        assert profile["motifs"]["nmos:shared_gate_pair"] == 1_999_000
        print(json.dumps({"devices": 2000, "profile_seconds": round(elapsed, 3)}))
        assert elapsed < 1.5, "Large fanout must not enumerate every device pair"
        return
    settings = Settings.local()
    catalog = Catalog(settings.state, settings.corpus, settings.upstream)
    references = ["1004", "1009", "1030", "2030", "366", "367"]
    report = {"descriptor_version": VERSION, "references": {}}
    if args.baseline:
        with catalog.connect() as db:
            rows = db.execute("SELECT id,topology,descriptor_version FROM vectors ORDER BY id").fetchall()
        report["descriptor_version"] = rows[0]["descriptor_version"]
        ids = [row["id"] for row in rows]
        matrix = np.stack([np.frombuffer(row["topology"], dtype=np.float32) for row in rows])
        for ref in references:
            ref = "analoggenie:" + ref
            start = time.perf_counter()
            scores = matrix @ matrix[ids.index(ref)]
            order = sorted(range(len(ids)), key=lambda i: (-float(scores[i]), ids[i]))
            report["references"][ref] = {"elapsed_ms": round((time.perf_counter()-start)*1000, 2),
                "neighbors": [{"id": ids[i], "topology_score": round(float(scores[i]), 6)}
                              for i in order if ids[i] != ref][:10]}
        path = settings.state / "topology-baseline-v2.json"
    else:
        retrieval = Retrieval(catalog)
        for ref in references:
            ref = "analoggenie:" + ref
            start = time.perf_counter()
            result = retrieval.search(reference_id=ref, limit=10)
            report["references"][ref] = {"elapsed_ms": round((time.perf_counter()-start)*1000, 2),
                "neighbors": [{k: item[k] for k in ("id", "topology_score", "structural_score")}
                              for item in result["items"]]}
        path = settings.state / "topology-comparison-v3.json"
        baseline = settings.state / "topology-baseline-v2.json"
        if baseline.exists():
            report["baseline"] = json.loads(baseline.read_text())
        report["limitations"] = "Six reference rankings and structural fixture tests; no broad circuit-family or electrical-spec accuracy claim. Baseline timing excludes catalog loading and reranking, so timings are not like-for-like."
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(path)
    print(json.dumps({ref: {"elapsed_ms": data["elapsed_ms"], "top_ids": [r["id"] for r in data["neighbors"][:5]]}
                      for ref, data in report["references"].items()}, indent=2))


if __name__ == "__main__":
    main()
