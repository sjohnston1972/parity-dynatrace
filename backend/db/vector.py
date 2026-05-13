"""ChromaDB vector store for finding deduplication and historical search.

Collections:
  - historical_findings: embedded findings for semantic similarity dedup
"""

import structlog

from db.chromadb import chroma_client

log = structlog.get_logger()

FINDINGS_COLLECTION = "historical_findings"


def _get_collection():
    """Get or create the findings collection."""
    return chroma_client.get_or_create_collection(
        name=FINDINGS_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def embed_finding(
    finding_id: str,
    device_id: str,
    title: str,
    description: str,
    category: str,
    severity: str,
    affected_entity: str,
    snapshot_id: str,
):
    """Store a finding embedding in ChromaDB for future dedup lookups."""
    try:
        collection = _get_collection()
        doc = f"{title}\n{description}\nEntity: {affected_entity}"
        collection.upsert(
            ids=[finding_id],
            documents=[doc],
            metadatas=[{
                "device_id": device_id,
                "category": category,
                "severity": severity,
                "affected_entity": affected_entity,
                "snapshot_id": snapshot_id,
            }],
        )
    except Exception as e:
        log.warning("vector_embed_failed", finding_id=finding_id, error=str(e))


def find_similar(
    device_id: str,
    title: str,
    description: str,
    affected_entity: str,
    exclude_snapshot_id: str,
    threshold: float = 0.15,
) -> list[dict]:
    """Search for semantically similar findings on the same device.

    Returns matches with distance < threshold (cosine).
    Lower distance = more similar. 0.15 is a tight match for near-duplicates.

    Filters: same device_id (always), same affected_entity (when provided)
    so we don't accidentally dedupe two distinct issues just because their
    titles read similarly. e.g. 'BGP neighbor 192.168.1.1 down' and
    'BGP neighbor 192.168.1.5 down' are DIFFERENT incidents — same device,
    same general problem class, different peers.
    """
    try:
        collection = _get_collection()
        if collection.count() == 0:
            return []

        doc = f"{title}\n{description}\nEntity: {affected_entity}"
        # Chroma's $and expects multiple sub-conditions. Skip the entity
        # filter if affected_entity is empty.
        if affected_entity:
            where = {"$and": [
                {"device_id": device_id},
                {"affected_entity": affected_entity},
            ]}
        else:
            where = {"device_id": device_id}

        results = collection.query(
            query_texts=[doc],
            n_results=5,
            where=where,
        )

        matches = []
        if results and results["ids"] and results["ids"][0]:
            for i, fid in enumerate(results["ids"][0]):
                dist = results["distances"][0][i] if results.get("distances") else 1.0
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                # Skip findings from the same snapshot (we already clean those)
                if meta.get("snapshot_id") == exclude_snapshot_id:
                    continue
                if dist < threshold:
                    matches.append({
                        "finding_id": fid,
                        "distance": dist,
                        "metadata": meta,
                    })
        return matches
    except Exception as e:
        log.warning("vector_search_failed", error=str(e))
        return []


def delete_finding(finding_id: str):
    """Remove a finding from the vector store (e.g. on dismiss)."""
    try:
        collection = _get_collection()
        collection.delete(ids=[finding_id])
    except Exception as e:
        log.warning("vector_delete_failed", finding_id=finding_id, error=str(e))


def delete_by_snapshot(snapshot_id: str):
    """Remove all findings for a snapshot from the vector store."""
    try:
        collection = _get_collection()
        # ChromaDB requires IDs for deletion — query first
        results = collection.get(
            where={"snapshot_id": snapshot_id},
        )
        if results and results["ids"]:
            collection.delete(ids=results["ids"])
    except Exception as e:
        log.warning("vector_delete_snapshot_failed", snapshot_id=snapshot_id, error=str(e))
