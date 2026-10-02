MATCH (c:Circuit)-[:HAS_DEVICE]->(q1:Device {canonical_type: 'npn'})
      -[:CONNECTED_TO {terminal: 'emitter'}]->(shared:Net)
MATCH (c)-[:HAS_DEVICE]->(q2:Device {canonical_type: 'npn'})
      -[:CONNECTED_TO {terminal: 'emitter'}]->(shared)
MATCH (q1)-[:CONNECTED_TO {terminal: 'base'}]->(base1:Net)
MATCH (q2)-[:CONNECTED_TO {terminal: 'base'}]->(base2:Net)
WHERE q1.id < q2.id AND base1 <> base2
RETURN c.id AS circuit_id,
       q1.source_instance AS transistor_1,
       q2.source_instance AS transistor_2,
       shared.name AS shared_emitter_net,
       'http://127.0.0.1:8765/analoggenie_' + split(c.id, ':')[1] + '.html' AS graph_url
LIMIT 25;
