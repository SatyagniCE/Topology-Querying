# Local circuit research workbench

User brief: local single-user application; defer semantic metadata enrichment and
use source metadata already available. Build browser inspection, editable user
metadata, validated upload, Cypher querying and hybrid text/topology retrieval.
Natural-language-to-Cypher is deferred; text similarity search is available.

## Product

Dark charcoal and warm paper typography, muted copper/olive accents. A library
with compact rows and filtering opens a full circuit inspector. Graph, schematic,
netlist and metadata tabs avoid displaying every panel simultaneously. A dedicated
query workspace has Cypher and similarity modes, result rows, graph output,
parameters, history, examples and clear empty/error states. Keyboard navigation,
responsive layouts, loading states and persistent URL state are required.

## Data and services

FastAPI serves a static browser UI and a local SQLite catalog under output/workbench.
Canonical records remain the authoritative topology. SQLite holds user edits,
uploaded records, source references, vectors, history and synchronization state.
NetworkX reconstructs each graph from the canonical JSON. Neo4j is queried live
for its graph view; missing or stale circuits are explicitly identified. Existing
source reference text is displayed and embedded without new LLM enrichment.

Edits are versioned with optimistic concurrency. User values take precedence.
Successful saves update searchable text and its embedding. Derived topology is
recomputed from the immutable netlist during an entry rebuild; V1 replaces netlists through a new upload.
Neo4j synchronization stores flat user properties and vector properties separately
from record_json. Failures leave durable pending synchronization and a visible retry.

## Retrieval

BAAI/bge-small-en-v1.5 via FastEmbed runs locally after one model download. A
terminal-aware WL neighborhood fingerprint, port shape and component profile
represent topology without training. Rails are typed by role; arbitrary instance
and internal net names are excluded. Text queries use semantic search; adding a
reference circuit combines independently ranked semantic and topology candidates
using reciprocal rank fusion. Reference-only searches use topology. Scores are
similarity measures, never probabilities or topology certification. Explanations
show count/I/O differences and provenance. At 3,350–10,000 circuits exact vector
scoring in NumPy is adequate; vectors are mirrored to Neo4j native vector indexes
for direct Cypher use. No GDS installation required.

## Upload

Required: nonempty description and valid supported netlist. Optional title, ports,
family, topology, stage count, I/O mode, tags, notes and PNG/JPEG schematic. Support
the repo's parenthesized Spectre-style format and basic flat SPICE R/C/L/M/Q/D/V/I
statements with explicit model typing. Reject unresolved subcircuits, unsupported
directives/types, duplicates, bad arity and unknown MOS/BJT polarity. Never guess
electrical operating specs or silently rewrite user classifications. A preview
shows parsed counts, supplied ports and source-located errors.
Deduplicate uploaded netlist hashes. Files and circuit IDs use server-owned UUIDs.

## Cypher

Workstation query console executes read-only statements. EXPLAIN must report a
read query; procedure calls, external imports and transaction/admin statements
are disallowed. Bounded transaction timeout and result limit protect the UI.
Result serialization handles nodes, relationships, paths, maps, lists and scalars;
graph and table views preserve useful circuit links. Errors do not erase drafts.
An offline Neo4j does not prevent library use, upload, edits or local retrieval.

## Verification

Unit/integration tests cover metadata persistence and conflicts, uploads and
duplicate validation, rename-invariant topology descriptors, retrieval changes
after edits, traversal-resistant file serving and query read guards. Run the
existing suite. Use the browser as a researcher: inspect 1004, switch graph
backends, read its original schematic/netlist, execute exact motif Cypher,
search similar circuits, edit/save/refresh, upload a valid circuit, reject an
invalid upload and exercise query errors. Inspect desktop and narrow viewport
screenshots and fix navigation, overflow, contrast and state problems.
