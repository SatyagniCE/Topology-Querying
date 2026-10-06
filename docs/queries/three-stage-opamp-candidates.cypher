// Diagnostic candidate template, not a verified three-stage op-amp classifier.
// Tested on the local corpus on 2026-10-06: zero matches.
// Looks for a VIN-named differential pair and two further common-source
// drain-to-gate connections terminating at a VOUT-named port.
// Excludes diode-connected intermediate nodes, external intermediate nets,
// and declared clock ports. Can miss valid architectures outside this template.
// Unknown device operating points and electrical performance are not checked.

MATCH (c:Circuit)-[:HAS_PORT]->(pi:Port)-[:MAPS_TO]->(input:Net)
WHERE toUpper(pi.name) STARTS WITH 'VIN'
MATCH (c)-[:HAS_DEVICE]->(a:Device)-[:CONNECTED_TO {terminal:'gate'}]->(input)
WHERE a.canonical_type IN ['nmos','pmos']
MATCH (a)-[:CONNECTED_TO {terminal:'source'}]->(tail:Net)
MATCH (c)-[:HAS_DEVICE]->(b:Device)-[:CONNECTED_TO {terminal:'source'}]->(tail)
MATCH (b)-[:CONNECTED_TO {terminal:'gate'}]->(input2:Net)<-[:MAPS_TO]-(pi2:Port)<-[:HAS_PORT]-(c)
WHERE a <> b AND a.canonical_type=b.canonical_type
  AND input <> input2 AND toUpper(pi2.name) STARTS WITH 'VIN'
  AND NOT toUpper(tail.name) IN ['VDD','VSS','VCC','VEE','GND','0','VDD!','VSS!']
MATCH (a)-[:CONNECTED_TO {terminal:'drain'}]->(n1:Net)
MATCH (c)-[:HAS_DEVICE]->(s2:Device)-[:CONNECTED_TO {terminal:'gate'}]->(n1)
MATCH (s2)-[:CONNECTED_TO {terminal:'drain'}]->(n2:Net)
MATCH (s2)-[:CONNECTED_TO {terminal:'source'}]->(rail2:Net)
MATCH (c)-[:HAS_DEVICE]->(s3:Device)-[:CONNECTED_TO {terminal:'gate'}]->(n2)
MATCH (s3)-[:CONNECTED_TO {terminal:'drain'}]->(out:Net)<-[:MAPS_TO]-(po:Port)<-[:HAS_PORT]-(c)
MATCH (s3)-[:CONNECTED_TO {terminal:'source'}]->(rail3:Net)
WHERE s2.canonical_type IN ['nmos','pmos'] AND s3.canonical_type IN ['nmos','pmos']
  AND toUpper(po.name) STARTS WITH 'VOUT'
  AND toUpper(rail2.name) IN ['VDD','VSS','VCC','VEE','GND','0','VDD!','VSS!']
  AND toUpper(rail3.name) IN ['VDD','VSS','VCC','VEE','GND','0','VDD!','VSS!']
  AND n1 <> n2 AND n2 <> out AND n1 <> out
  AND NOT s2 IN [a,b] AND NOT s3 IN [a,b,s2]

  AND NOT EXISTS {
    MATCH (c)-[:HAS_DEVICE]->(diode:Device)-[:CONNECTED_TO {terminal:'gate'}]->(n1)
    MATCH (diode)-[:CONNECTED_TO {terminal:'drain'}]->(n1)
    WHERE diode.canonical_type IN ['nmos','pmos']
  }
  AND NOT EXISTS {
    MATCH (c)-[:HAS_DEVICE]->(diode:Device)-[:CONNECTED_TO {terminal:'gate'}]->(n2)
    MATCH (diode)-[:CONNECTED_TO {terminal:'drain'}]->(n2)
    WHERE diode.canonical_type IN ['nmos','pmos']
  }
  AND NOT EXISTS { MATCH (c)-[:HAS_PORT]->(:Port)-[:MAPS_TO]->(n1) }
  AND NOT EXISTS { MATCH (c)-[:HAS_PORT]->(:Port)-[:MAPS_TO]->(n2) }
  AND NOT EXISTS {
    MATCH (c)-[:HAS_PORT]->(clk:Port)
    WHERE toUpper(clk.name) CONTAINS 'CLK' OR toUpper(clk.name) CONTAINS 'CLOCK'
  }
RETURN DISTINCT c.id AS circuit_id, a.source_instance AS input_device,
  b.source_instance AS other_input, n1.name AS stage1_output,
  s2.source_instance AS stage2_device, n2.name AS stage2_output,
  s3.source_instance AS stage3_device, out.name AS output
ORDER BY circuit_id LIMIT 20
