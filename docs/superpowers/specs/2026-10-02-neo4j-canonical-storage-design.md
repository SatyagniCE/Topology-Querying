# Neo4j storage for canonical circuit records

Date: 2026-10-02

## Purpose and scope

Store the valid AnalogGenie `CircuitRecord` corpus in a local Neo4j Community database so device and net patterns can be queried across circuits. The versioned canonical JSON records remain the import boundary. The first release supports import, repeat import, local operation, and Cypher pattern queries. It does not import the separately derived `DeviceGraph` format.

## Local runtime

The machine currently has Java 8, no Docker or Podman executable, and no noninteractive sudo. Download a Linux x64 Temurin 21 JRE tarball and its published SHA-256 checksum, verify it, and extract it under `~/.local/opt/`. Download and extract a pinned Neo4j Community Linux tarball under the same user-owned directory. The start script sets `JAVA_HOME` and prepends its `bin` directory to `PATH` for that Neo4j process only. No system Java setting, package manager, `/opt`, or root-owned path is changed.

Neo4j binds HTTP and Bolt to localhost. Put its data and logs in user-owned paths, and set an initial password before first start. Keep credentials outside the repository in a user-owned file with mode `0600`; the import command reads URI, username, password, and database name from environment variables. Provide start, stop, status, and connectivity instructions. Do not add generated database files or credentials to Git.

## Graph model

Every imported record has one `(:Circuit {id})` node. It links to its `(:Device {id})`, `(:Net {id})`, and `(:Port {id})` nodes via `HAS_DEVICE`, `HAS_NET`, and `HAS_PORT`. Each canonical `Connection` becomes one directed `(:Device)-[:CONNECTED_TO {terminal, terminal_ordinal}]->(:Net)` relationship. Each canonical `PortRecord` becomes a separate Port node with one `(:Port)-[:MAPS_TO]->(:Net)` relationship to its `net_id`. A port's Net remains present even if its device degree is zero. Net properties include `name`, `is_external`, and `degree_by_terminal`; Device properties include `source_instance`, `ordinal`, `canonical_type`, `raw_type`, and `category`. Port properties include `name`, `ordinal`, and `referenced_by_device`. Port order is queried through `MAPS_TO`, so `port_ordinal` is not duplicated on the materialized Net node; its original value remains in the complete serialized `CircuitRecord`.

The importer derives `Port.id` as `<circuit_id>:port:<six-digit zero-padded ordinal>` because `PortRecord` has no ID field. Other IDs come directly from the canonical records. Preserve the complete versioned `CircuitRecord` as serialized JSON on the Circuit node for fields not useful as graph properties, including source provenance, parameters, and issues. Materialized graph properties and relationships must agree with that record. The Device/Net/Port nodes and their `CONNECTED_TO`/`MAPS_TO` edges come from a pure canonical-record projection that can also be consumed by an in-process graph builder; Neo4j adds the Circuit ownership layer.

Create these four uniqueness constraints before import:

```cypher
CREATE CONSTRAINT circuit_id_unique IF NOT EXISTS FOR (c:Circuit) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT device_id_unique IF NOT EXISTS FOR (d:Device) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT net_id_unique IF NOT EXISTS FOR (n:Net) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT port_id_unique IF NOT EXISTS FOR (p:Port) REQUIRE p.id IS UNIQUE;
```

## Import behavior

The CLI reads `circuits/*.json` produced by `circuit-ingest parse-analoggenie`, validates each file as a `CircuitRecord`, and checks its internal references before writing. It creates constraints first, then replaces one circuit's existing subgraph and its complete JSON in one managed write transaction. A failed transaction leaves the previous version of that circuit intact. Replacement removes its old relationships and owned Device, Net, and Port nodes before creating the new graph, preventing duplicate terminal relationships on repeat import. IDs are scoped to circuits, so one circuit's replacement does not alter another. The import command reports circuit-level failures and a final summary; it must not report success if any record failed.

The first load covers all valid corpus records. Quarantined or failed records have no circuit JSON and are never inserted. Query examples must show a device type connected to a named net, and a Port mapped to an unreferenced net, with circuit IDs returned.

## Verification

Use a small fixture to verify relationship direction, terminal and ordinal preservation, a port with zero device degree, failed-transaction rollback, and a device/net pattern query. Check live database connectivity before import.

After full import, run Cypher counts and compare them with expected values read at verification time from `analoggenie-audit-report.json`: the sum of valid and valid-with-warnings statuses for Circuit nodes, `totals.devices` for Device nodes, `totals.nets` for Net nodes, `totals.ports` for Port nodes and `MAPS_TO` relationships, and `totals.connections` for `CONNECTED_TO` relationships. Group Device nodes by `canonical_type` in Cypher and diff every type count against `canonical_device_type_counts` in the same report. Do not hardcode corpus-wide counts in verification code or scripts. Confirm every Port has exactly one mapped Net and each `CONNECTED_TO` endpoint belongs to the same Circuit.

Run this manual spot-check after import and require exactly one row with net `0`:

```cypher
MATCH (c:Circuit {id: 'analoggenie:755'})-[:HAS_DEVICE]->
      (d:Device {source_instance: 'Q30'})-
      [r:CONNECTED_TO {terminal: 'substrate'}]->(n:Net {name: '0'})
RETURN c.id AS circuit_id, d.id AS device_id,
       r.terminal AS terminal, r.terminal_ordinal AS terminal_ordinal,
       n.name AS net;
```

The source netlist line is `Q30 (net91 net62 VSS 0) npn`; this check specifically verifies the fourth BJT terminal survived into Neo4j. Run the full import a second time and require identical counts for every node label and relationship type. Record these audit results in command output for review.

## References

- Neo4j Linux tarball: https://neo4j.com/docs/operations-manual/current/installation/linux/tarball/
- Neo4j Java requirements: https://neo4j.com/docs/operations-manual/current/installation/requirements/
- Neo4j Python managed transactions: https://neo4j.com/docs/python-manual/current/transactions/
- Neo4j uniqueness constraints: https://neo4j.com/docs/cypher-manual/current/schema/syntax/
- Temurin 21 downloads: https://adoptium.net/temurin/releases?version=21
