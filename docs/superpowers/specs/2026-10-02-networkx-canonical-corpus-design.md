# NetworkX representation of the canonical circuit corpus

Date: 2026-10-02

## Purpose and boundary

Build one in-process NetworkX graph per valid AnalogGenie `CircuitRecord` in `circuits/*.json`. Each graph is keyed by the record's `circuit_id`; circuits are never merged or connected to each other, and no net is shared across circuits. This representation supports in-process graph algorithms and later feature or embedding generation. It is an independent consumer of canonical JSON and neither replaces nor requires a running Neo4j instance. The parser's versioned canonical JSON remains the source of truth.

## Shared construction decision

The canonical record already exposes every Device, Net, Port, terminal contact, and port mapping needed by both backends. Factor that transformation into a pure `circuit_ingest.canonical_graph.project_circuit(record)` function. It validates the record and returns ordered typed node and edge descriptions with stable IDs, kinds, properties, and endpoints. It preserves one `CONNECTED_TO` edge per `Connection`, including multiple terminal contacts from the same Device to the same Net, and one `MAPS_TO` edge per Port. Both the Neo4j importer and NetworkX builder consume this projection. Neither backend independently interprets terminal order, derives Port IDs, or chooses materialized properties.

The projection covers Device/Net/Port nodes and `CONNECTED_TO`/`MAPS_TO` edges. Neo4j adds a `Circuit` node and `HAS_DEVICE`/`HAS_NET`/`HAS_PORT` ownership relationships; NetworkX uses one graph container per circuit with the Circuit metadata in graph attributes. That ownership difference is intentional and does not change the shared circuit topology. Unit tests compare NetworkX's normalized nodes and edges to the projection. Live Neo4j integration tests compare Neo4j's corresponding subgraph to the same projection. The corpus audit independently checks totals in each backend, so an adapter bug that drops or duplicates elements is detectable even though both call the same function.

## Graph type, schema, and IDs

Use `networkx.MultiDiGraph`. Connections point from Device to Net and port mappings point from Port to Net. A `DiGraph` would collapse two terminals on one Device that land on the same Net; `MultiDiGraph` preserves both as distinct keyed edges. Its support for directed parallel edges matches this circuit model. [NetworkX graph types](https://networkx.org/documentation/stable/reference/classes/index.html)

Node IDs are exactly the Neo4j/global IDs: canonical `DeviceRecord.id` and `NetRecord.id`, plus the shared projection's `<circuit_id>:port:<six-digit zero-padded ordinal>` for Ports. There is no NetworkX-specific renumbering. Each node has `kind` (`Device`, `Net`, or `Port`) plus exactly the materialized properties named in the [Neo4j design](2026-10-02-neo4j-canonical-storage-design.md): Device `source_instance`, `ordinal`, `canonical_type`, `raw_type`, `category`; Net `name`, `is_external`, `degree_by_terminal`; Port `name`, `ordinal`, `referenced_by_device`. The original `NetRecord.port_ordinal` stays only in the full canonical JSON, as in Neo4j.

Each `CONNECTED_TO` edge carries `kind='CONNECTED_TO'`, `terminal`, and `terminal_ordinal`. Its stable MultiDiGraph key is `CONNECTED_TO:<terminal_ordinal>` for its Device→Net pair. Each `MAPS_TO` edge carries `kind='MAPS_TO'` and uses key `MAPS_TO`. No inferred device-to-device edges are added. Graph attributes include `circuit_id`, `schema_version`, `dataset`, and the complete deterministic serialized `CircuitRecord` as `record_json`, mirroring Neo4j's Circuit-level preservation. The graph contains zero-degree external Nets and their Ports, so a declared but unreferenced port remains visible through `MAPS_TO`.

## Build, storage, and loading

The builder reads each `circuits/*.json`, validates it as `CircuitRecord`, calls the shared projection, and creates one `MultiDiGraph`. It writes one file per circuit and a manifest keyed by `circuit_id` that records the relative path and source-record hash. Build order is sorted by `circuit_id`; output paths are derived from safe canonical IDs. A caller may load one graph by ID or iterate the corpus without keeping every graph in memory at once. A build failure is reported for the specific circuit and must not leave a partial output file.

Use Python pickle as the primary graph cache: it preserves the NetworkX graph type, edge keys, and Python attribute types without a custom decoder and is quick to reload. Write atomically, then load only artifacts generated in this trusted local workflow; Python pickle must not be used on untrusted files. A second portable graph export is not part of this first release: the canonical JSON is already portable and can regenerate every graph. If graph interchange becomes necessary, prefer NetworkX node-link JSON because it carries multigraph edge keys; GraphML would require extra attribute-type and round-trip checks. [NetworkX node-link format](https://networkx.org/documentation/stable/reference/readwrite/generated/networkx.readwrite.json_graph.node_link_data.html), [GraphML support](https://networkx.org/documentation/stable/reference/readwrite/graphml.html)

## Verification

Fixture tests cover relationship direction, all terminal and ordinal properties, two Device terminals connecting to one Net, duplicate source-instance names retaining separate IDs, and an unreferenced Port mapped to a zero-degree Net. Test one graph's node and edge signature against the shared projection and test a pickle round trip for type, IDs, keys, properties, and `record_json`. Neo4j's corresponding integration test compares its materialized Device/Net/Port topology to that same projection.

For the full corpus, read expected values dynamically from `analoggenie-audit-report.json` at verification time: Circuit graph count from `status_counts.valid + status_counts.valid_with_warnings`; Device, Net, and Port node totals from `totals.devices`, `totals.nets`, and `totals.ports`; `CONNECTED_TO` and `MAPS_TO` edge totals from `totals.connections` and `totals.ports`; and per-type Device counts from `canonical_device_type_counts`. Do not copy corpus-wide count literals into verifier code.

Perform the NetworkX-native spot-check on graph `analoggenie:755`: find the Device with `source_instance='Q30'`, then require exactly one outgoing `CONNECTED_TO` edge with `terminal='substrate'` and `terminal_ordinal=3` to the Net whose `name='0'`. The source line is `Q30 (net91 net62 VSS 0) npn`. Finally, rebuild the entire corpus twice from unchanged canonical JSON and compare every circuit's normalized graph signature, including graph attributes, node attributes, directed endpoints, edge keys, and edge attributes. Identical signatures and corpus totals are the required determinism evidence; pickle bytes themselves are not the comparison target.
