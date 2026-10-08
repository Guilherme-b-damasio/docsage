# Retrieval

docsage ranks chunks with BM25. Each query term contributes according to how rare it
is across the index and how often it appears in the chunk.

# Chunking

Markdown files are split on headings so every chunk keeps its section path. Other files
use a sliding window of words with some overlap between neighbouring chunks.
