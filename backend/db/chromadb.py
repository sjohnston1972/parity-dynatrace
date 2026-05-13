"""ChromaDB client setup."""

import chromadb

from config import settings

chroma_client = chromadb.HttpClient(
    host=settings.chromadb_host,
    port=settings.chromadb_port,
)
