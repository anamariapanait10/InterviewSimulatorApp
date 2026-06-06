This folder contains local data used by the backend.

Structure:

- `company_knowledge_rag/`
  Raw source documents for the company knowledge RAG.
- `problem_catalog_rag/`
  Raw source documents for the coding problem catalog RAG.
- `chroma/`
  Persistent local vector store for the company knowledge RAG.
- `problem_chroma/`
  Persistent local vector store for the coding problem catalog RAG.

The `*_rag/raw/` folders are intended to hold source material before indexing.
