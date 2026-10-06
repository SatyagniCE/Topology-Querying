// Manual hybrid retrieval example, verified against the local Neo4j database.
// Parameters:
//   reference_id: circuit ID, e.g. analoggenie:1004
//   text_vector: 384-number query embedding from BAAI/bge-small-en-v1.5
// Plain text is NOT accepted as text_vector; generate it outside Cypher first.
// Retrieves up to 100 candidates from each vector index and fuses their ranks.
// This is not identical to the Similarity UI, which scores ALL eligible local
// vectors exactly, then fully rescores its top 100 topology candidates in Python.
// This recipe does not run that reranker. Candidate caps and Neo4j approximate
// search can also change order.
// The similarity scores and fused scores do not certify circuit function/specs.

MATCH (ref:Circuit {id:$reference_id})
CALL {
  WITH ref
  MATCH (c:Circuit)
  SEARCH c IN (
    VECTOR INDEX circuit_semantic_idx
    FOR $text_vector
    LIMIT 100
  ) SCORE AS similarity
  WITH c,ref,similarity WHERE c<>ref
  ORDER BY similarity DESC,c.id
  WITH collect(c.id) AS ids
  UNWIND range(0,size(ids)-1) AS i
  RETURN ids[i] AS circuit_id,1.0/(61+i) AS contribution,'text' AS source
  UNION ALL
  WITH ref
  MATCH (c:Circuit)
  SEARCH c IN (
    VECTOR INDEX circuit_topology_idx
    FOR ref.topology_embedding
    LIMIT 100
  ) SCORE AS similarity
  WITH c,ref,similarity WHERE c<>ref
  ORDER BY similarity DESC,c.id
  WITH collect(c.id) AS ids
  UNWIND range(0,size(ids)-1) AS i
  RETURN ids[i] AS circuit_id,1.0/(61+i) AS contribution,'topology' AS source
}
RETURN circuit_id,sum(contribution) AS hybrid_score,
       collect(source) AS matched_rankings
ORDER BY hybrid_score DESC,circuit_id
LIMIT 10
