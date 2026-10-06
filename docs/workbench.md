# Circuit Atlas — local V1 guide

## What is built

A local research workbench over the 3,350 canonical AnalogGenie circuits. It
includes a searchable library, NetworkX and live Neo4j graphs, available original
schematics, source netlists, existing provenance/reference text, editable user
annotations, validated circuit uploads, a read-only Cypher console and hybrid
similarity retrieval. A clean setup contains 3,350 canonical records.
During earlier testing on the author's Mac, one labelled common-source demo
upload was retained, making that machine's local catalog 3,351 records; this
demo/local state is not bundled for new users.

The application does not use a hosted LLM, train a model, invent circuit labels,
infer electrical specifications, or translate natural language into Cypher.
Metadata enrichment is deferred as requested. Natural-language **similarity
search** is implemented; it is different from translating structural questions
into database queries.

## Setup and start

For a fresh machine, follow [the setup guide](setup.md): install Git, Python
3.11–3.13 and Docker, then run `bash scripts/setup-workbench.sh`. Mac users can
double-click **Setup.command**, then **Launch.command**. See [the main README](../README.md)
for the capability/limitation overview and [CONTRIBUTING.md](../CONTRIBUTING.md)
for collaboration. The commands below assume setup has completed.

From the project directory:

```bash
bash scripts/run-workbench.sh
```

The launcher opens <http://127.0.0.1:8766/> after the app responds; leave its
terminal running. Ctrl+C stops the UI. It starts/reuses the
`topology-querying-neo4j` Docker container when needed. It does not install
Docker or a separate system Neo4j runtime. The app reads the
existing container's connection credentials locally, without displaying them.
There is no Circuit Atlas login because this V1 is single-user and loopback-only.

The first index build downloads BGE-small once (about 67 MB model weights), then
embeds the corpus on this machine. Subsequent starts reuse cached vectors.
The health button in the footer shows indexing and Neo4j synchronization state.
Retry indexing/sync there if either service reports an error.

For the supported fresh-machine workflow:

```bash
bash scripts/setup-workbench.sh
bash scripts/run-workbench.sh
```

Setup creates/reuses the local database, adds only missing catalog circuits,
and builds/synchronizes the indexes. Do not use the legacy
`circuit_ingest.neo4j_cli import` as routine setup or recovery: it replaces
existing circuit nodes/properties. Existing installations need no full re-import.
The launcher defaults to opening a browser; add `--no-open` to suppress it.
Use `bash scripts/run-workbench.sh --doctor` for read-only diagnosis.

Custom connection variables: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`,
`NEO4J_DATABASE`. Set credentials privately in your shell, not in committed code.
`CIRCUIT_STATE` can change the local state directory. A different UI port is
available with `bash scripts/run-workbench.sh --port 8767`.

The launcher explicitly sets the project source path. This also avoids a macOS
environment issue observed here: Python 3.13 ignores editable-install `.pth`
files if the OS has marked them hidden.

## Researcher workflow

1. Search the Library for `1004`, or filter by dataset/device type. Open a row.
2. In Graph, switch between NetworkX and Neo4j. Both show the same terminal-level
   connections. Rails and separate port nodes are hidden initially to reduce
   clutter; their toggles change the display, not the stored graph. Select a
   device to inspect its properties and terminal-to-net connections.
   The enlarged viewer has incremental − / + zoom controls, a percentage
   indicator and Fit. Expand opens the same panel in a full-window dialog;
   Close or Escape returns it to the page. The backend switch selects two
   ways to access the same circuit model, not two distinct circuit topologies.
   Circuit details now use the remaining window height, with compact page
   controls. Long facts/netlists scroll inside their panels, not the page.
   On narrow screens, Details opens a facts drawer; Hide details or Escape
   closes it. Library and Query page layout is unchanged.
3. Use Schematic to inspect the original book/Cadence figure when available.
   Schematics have − / +, Fit and 1:1 original-size controls; scroll to pan
   enlarged images. Schematic and Netlist panels also support Expand. Netlist
   shows the source text and offers copy/download.
4. Metadata separates existing source facts from researcher annotations. No
   family, topology, stage count or performance is automatically asserted.
   Save a user annotation to update local search text and queue its embedding
   refresh and Neo4j synchronization. Existing user entries are not overwritten.
5. Find similar opens reference-only topology search. Add text for hybrid
   retrieval, or leave the reference blank for text-only retrieval. Click any
   candidate to inspect the actual wiring and schematic.
6. Query this graph opens parameterized Cypher for the current circuit. Run it,
   then choose Graph to visualize returned nodes/relationships. Scalar circuit
   IDs link back to the full inspector. Query drafts and successful history are
   retained; JSON parameters and result downloads are available.

NetworkX's JSON button exports real node-link data for a directed multigraph:

```python
import json
import networkx as nx

with open("circuit.networkx.json") as handle:
    graph = nx.node_link_graph(json.load(handle), edges="edges")
```

The Neo4j JSON button exports the normalized live graph response. Circuit JSON
downloads are the immutable canonical source record; editable annotations are
stored separately in the local catalog and on Neo4j Circuit properties.

## Cypher capabilities and examples

The console supports structural `MATCH`/`WHERE`/`RETURN`, aggregation, paths,
read subqueries and native vector `SEARCH`. It rejects writes, procedures, admin
commands and external imports. Queries have a 10-second transaction timeout and
default 200-row display cap. Graph rendering caps at 1,200 nodes / 3,000 edges and
shows a warning when truncated. Large returned lists show an explicit truncation
wrapper above 1,000 elements. Narrow large queries rather than treating a partial
visualization as the whole circuit.

The sidebar includes inventory, circuit 1004 inspection, NMOS mirror **candidates**
and topology-neighbour examples. These were executed against the live database.
Examples below are read-only.

The diagnostic [three-stage candidate query](queries/three-stage-opamp-candidates.cypher)
was also executed. A looser three-transistor connection-chain query returned
1004/1030 and clocked comparator false positives. For 1004, the extra connection
passes through diode-connected net12/net30 current-mirror nodes; it is not
evidence of a third independent voltage-gain stage. The stricter template
excludes those nodes, intermediate external ports and declared clock ports,
and returned zero matches. This is not proof the corpus has no three-stage
op-amps: it covers only a specific common-source chain, relies on VIN/VOUT/rail
names, and does not determine operating points or simulate gain. No circuit
was assigned a stage-count label from these queries.

Inspect all terminal connections of 1004:

```cypher
MATCH (c:Circuit {id:'analoggenie:1004'})-[:HAS_DEVICE]->(d)
MATCH (d)-[r:CONNECTED_TO]->(n:Net)
RETURN d,r,n
LIMIT 100
```

Find its topology-vector neighbours through Neo4j:

```cypher
MATCH (ref:Circuit {id:'analoggenie:1004'})
MATCH (c:Circuit)
SEARCH c IN (
  VECTOR INDEX circuit_topology_idx
  FOR ref.topology_embedding
  LIMIT 21
) SCORE AS score
WITH c,ref,score WHERE c<>ref
RETURN c.id AS circuit_id,score
ORDER BY score DESC
LIMIT 20
```

Find user-annotated amplifiers without claiming to classify unannotated circuits:

```cypher
MATCH (c:Circuit)
WHERE c.family='amplifier'
RETURN c.id AS circuit_id,c.title,c.topology,c.description
LIMIT 20
```

Schema: `Circuit` owns `Device`, `Net`, `Port` through `HAS_DEVICE`, `HAS_NET`,
`HAS_PORT`. `Device`→`Net` uses `CONNECTED_TO` with `terminal` and
`terminal_ordinal`. `Port`→`Net` uses `MAPS_TO`. Useful fields include `c.id`,
`d.canonical_type`, `d.source_instance`, `n.name`. User properties include
`c.family`, `c.topology`, `c.stage_count`, `c.input_mode`, `c.output_mode`,
`c.tags`, `c.description`, `c.notes`, `c.metadata_revision`.

Vector indexes are `circuit_semantic_idx` (384 dimensions) and
`circuit_topology_idx` (768). Native `SEARCH` syntax is verified on the existing
Neo4j 2026.09 Community database; it does not require GDS. Neo4j vector scores are
bounded 0–1, whereas the local workbench displays raw cosine. Do not compare raw
scores across different retrieval sources. See the
[official Neo4j vector-index documentation](https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/).

## Uploading circuits

Use Add circuit. Paste a supported netlist or load a `.cir`, `.sp`, `.spice` or
`.txt` file, supply a basic description, then Validate netlist before saving.
Optional: title, external ports, user classifications, stage count, I/O modes,
tags, research notes and a PNG/JPEG schematic.

Typed parenthesized example:

```text
M1 (out in VSS VSS) nmos4 w=10u l=1u
R1 (VDD out) resistor r=10k
```

Flat SPICE example:

```text
* Resistively loaded amplifier
.model NMOD NMOS
M1 out in VSS VSS NMOD W=10u L=1u
R1 VDD out 10k
.end
```

Suggested ports: `VDD VSS in out`. They must refer to nets in the circuit.
SPICE names are case-insensitive, with first-observed spelling retained.
Parenthesized typed net names retain their spelling/case-sensitive connections.
Mixing these dialects in one upload is rejected.

V1 flat SPICE supports R/C/L, four-terminal MOS, three/four-terminal BJT, diode
and independent DC voltage/current sources. Explicit model polarity is required
for unfamiliar transistor model names. Values and dimensions are preserved,
not simulated or evaluated as performance. Uploads reject repeated instance
names, unresolved subcircuits, unknown types, unsupported directives/waveforms,
bad arity and missing ports. `.include`, `.subckt`, control blocks and PDK model
resolution are not supported. Netlists are limited to 1 MB / 2,000 devices;
schematics to 6 MB / 25 megapixels. Netlist hashes prevent exact duplicate uploads.

Upload validation means syntactically supported and structurally consistent,
not electrically functional, simulation-ready or compliant with a target spec.

## How retrieval actually works

There are separate paths:

- **Library search box:** case-insensitive substring lookup over IDs, saved
  annotations and source-reference text; no embedding model is involved.
- **Similarity / text only:** embed the query with the local BGE-small model,
  then compare it against saved text vectors using cosine.
- **Similarity / reference only:** compare the reference's terminal-aware
  descriptor against saved topology vectors using cosine, then rescore the
  top 100 candidates against full, uncompressed structural features.
- **Similarity / both inputs:** rank text and topology independently, then
  combine the two ranks. This is the current hybrid mode, not a jointly trained
  text–graph model or a merged vector.
- **Cypher:** execute exactly the supplied query. Ordinary MATCH/WHERE does not
  implicitly call an embedding model or apply hybrid ranking. Explicit vector
  SEARCH accesses the synchronized Neo4j vector indexes.

The [manual hybrid Cypher example](queries/hybrid-text-and-topology.cypher)
uses both indexes and reciprocal rank fusion. Supply `reference_id` plus a
384-number `text_vector` generated by the same local model; plain text cannot
be used directly as that vector. A caller can prepare the parameters with:

```python
import json
from fastembed import TextEmbedding

model = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir="output/workbench/model", threads=2)
vector = next(model.query_embed(["Differential amplifier with two output branches"]))
print(json.dumps({"reference_id": "analoggenie:1004", "text_vector": vector.tolist()}))
```

Paste that JSON into the console's Query parameters field and the example into
Cypher. It was executed successfully on the current database. It retrieves
100 candidates per index, whereas the Similarity UI compares all eligible vectors
locally and structurally rescores its top 100 topology candidates; the two
result orders need not match. The manual Cypher recipe does not run the Python
full-pattern rescoring step. For
ordinary research use, entering both inputs in Similarity avoids this manual
parameter preparation. Natural-language-to-Cypher is still not implemented.

The parser creates device–terminal–net relationships directly from the netlist.
NetworkX and Neo4j store/materialize those facts; neither learns circuit function.

Text retrieval uses the pretrained local `BAAI/bge-small-en-v1.5` model over
existing source-reference text, structural facts and supplied annotations.
Schematic pixels are shown for inspection but are not embedded or interpreted.
Book page references alone contain little semantic information, so text-only
results can be weak or misleading for unannotated circuits.

Topology retrieval uses the training-free `terminal-wl-v3` descriptor. Its 768
numbers contain 640 weighted WL pattern buckets (initial labels plus four
refinement levels), 32 device/count features, 32 port features and 64 explicit
motif features. Motifs include gate–drain ties, nonrail shared-source pairs,
shared-gate/mirror-like candidates, source–drain stacks and series RC wiring.
These are connection facts/candidates, not verified current mirrors, differential
pairs, cascodes or gain stages. Parallel RC is not counted as series RC.
WL patterns from all depths share the 640-bucket space with depth included in
each key. The wiring block is normalized as a whole so adding more depths does
not automatically outweigh all explicit I/O/motif evidence. Block weights are
engineering choices (counts 0.65, ports 1.0, motifs 0.9, wiring 1.0), not learned
parameters or probabilities; more representative circuit judgements are needed
before claiming general retrieval accuracy.
Ordinary resistor/capacitor/inductor pin order is ignored; transistor and diode
terminal distinctions remain. Component values/dimensions are not compared.
Rail nodes retain their role without dominating the neighbourhoods. Arbitrary
device/internal-net names are excluded, except known rail names used as hints.
Port roles are heuristic name interpretations, not verified functional labels.
This descriptor does not certify graph isomorphism, stage count or circuit family.

The local search compares eligible vectors with cosine, then reranks the top
100 topology candidates using the uncompressed WL pattern labels and the same
explicit feature blocks. This removes compact-vector bucket collisions from
that final comparison, but does not prove graph isomorphism. The UI reports
TOPOLOGY COSINE separately from FULL-PATTERN SCORE; returned order may differ
from raw cosine order. Hybrid search fuses text rank with this reranked topology
rank using `1/(60 + rank)` from each ranking. Text-dominant hybrid results outside
the topology shortlist have no full-pattern score. It does not average raw scores.
Vectors are also synchronized to Neo4j native approximate-neighbour indexes for
Cypher access. MATCH/WHERE queries remain available and unchanged. A vector-only
Cypher query uses the upgraded fingerprint, but not the Python reranker. The
current source corpus is 3,350 circuits, not a claimed 10,000-record
dataset. Scaling to 10,000 still needs a measured latency/quality check.

A regression case ranks 1009 above 2030 for topology similarity to 1004. The
v3 UI's top two full-pattern candidates in the measured corpus are 366 and
1009; vector-only ordering can differ. This is a useful check, not a broad
accuracy benchmark. Hybrid text can change that order. Inspect
candidate netlists; do not interpret cosine as a probability of meeting a spec.
Device counts, mirrors or long graph paths alone do not establish gain stages.

The WL-style retrieval code was introduced in the local workbench implementation;
it is absent from the checked-out GitHub baseline (`0a263ba`, also `origin/main`
at verification). The baseline already had parser/NetworkX/Neo4j graph tools.

On a descriptor-version change, restart the app to rebuild topology vectors and
sync Neo4j. Existing text vectors and researcher annotations are retained. Old
and new descriptor versions must not be compared. `scripts/benchmark-topology.py`
records six reference rankings and latency; its output is not a broad accuracy
benchmark. No new model, plugin or training is required for this upgrade.

### V3 verification on this Mac

- Full suite: 151 passed, 14 environment-gated skips; existing Starlette/httpx warning.
- Structural fixtures: ordinary passive pin reversal now scores 1.0 instead of
  0.728; a rewired three-MOS fixture scores 0.776 instead of 0.898. These values
  demonstrate those specific invariances/distinctions, not general accuracy.
- Large supported fanout: a 2,000-MOS profile retains the correct 1,999,000
  shared-gate pairs while taking about 0.07 seconds with grouped counting.
- All 3,351 local records and Neo4j Circuit nodes use 768-dimensional v3 vectors;
  checksum verification confirmed unchanged annotations and text embeddings.
- Six reference-only searches with full-pattern rescoring took about 0.8–0.9
  seconds during the measured local run. Baseline timings in the saved report
  cover a different code path and are not a speed comparison.
- Live API smoke and actual browser checks covered topology, hybrid, text-only,
  vector Cypher and ordinary MATCH/WHERE. The NMOS query for 1004 still returns
  seven devices; the strict three-stage diagnostic still returns zero candidates.
- Reference 1004 UI shortlist begins 366, 1009, 365, 367, 364. These remain
  unverified candidates. Vectors alone do not establish family/stage/spec labels.

Saved evidence: `output/workbench/topology-comparison-v3.json` includes the v2
reference rankings; `topology-v2-vectors.sqlite3` preserves the old generated
topology vectors (not a replacement for a full catalog backup).

## Persistence and maintenance

`output/workbench/catalog.sqlite3` holds uploaded canonical records, raw netlists,
user annotations/history, revision-matched vectors, query history and sync state.
`output/workbench/uploads/` holds optional uploaded images. `output/workbench/model/`
contains the reusable model cache. The directory is ignored by Git and stays on
this machine. At build time it occupied roughly 161 MB; this excludes the existing
Neo4j database, source dataset and Python environment.

User edits use optimistic revisions: stale tabs get a conflict instead of
silently replacing newer annotations. Vector writes also check the originating
revision; Neo4j sync only accepts matching current vectors. Offline failures
leave durable pending state and retry controls. The local library, NetworkX
and cached similarity retrieval do not require Neo4j to be online.

For a backup, stop the workbench cleanly, then copy the whole
`output/workbench/` directory, including any SQLite WAL/SHM files present. Preserve
the original corpus/submodule and Docker volume separately. Do not delete local
state as a troubleshooting shortcut: it contains user uploads and annotations.

Implementation modules are under `src/circuit_workbench`: `catalog.py` for
persistence, `uploads.py` for validation, `retrieval.py` for vectors/ranking,
`neo4j.py` for live queries/sync, `app.py` for HTTP endpoints and `static/` for UI.

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/python scripts/verify-workbench.py
```

The smoke script requires the UI and Neo4j running with indexing complete. It
checks live graph parity, schematic serving, standard NetworkX JSON, read-query
results, query guard/count preservation, vector search, all three retrieval
modes and invalid-upload rejection. It writes successful query history only;
it does not modify circuit content.

Browser checks cover desktop/narrow layouts, source inspection, graph backend
switching, query table/graph views, sample queries, upload validation, metadata
save/refresh, unsaved-navigation cancellation and hybrid retrieval. The retained
demo on the author's machine provides a safe record for trying edits. On a fresh
installation, upload your own small test circuit to try the editor.
Existing environment-gated integration tests remain separate from these live
workbench checks. Bulk semantic classification and an electrical retrieval
benchmark are deliberately not claimed.

Viewer zoom helpers can be checked with Node's built-in runner:
`node --test tests/ui/viewer-controls.test.mjs`. The browser lifecycle regression
in `tests/ui/viewer-browser-regression.mjs` exports a function accepting a CUA
tab already open on Query and a slow, zero-result query string (the strict
three-stage diagnostic query was used locally). It verifies that a previous
graph expanded during a pending query is dismissed when new results arrive.
