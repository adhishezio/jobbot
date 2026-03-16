import os

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - depends on runtime container
    genai = None


def _extract_embedding_values(result):
    if result is None:
        return None

    if isinstance(result, dict):
        if "embedding" in result and isinstance(result["embedding"], list):
            return result["embedding"]
        if "embedding" in result and isinstance(result["embedding"], dict):
            return result["embedding"].get("values")
        if "values" in result:
            return result["values"]

    embedding = getattr(result, "embedding", None)
    if embedding is not None:
        values = getattr(embedding, "values", None)
        if values is not None:
            return values
        if isinstance(embedding, list):
            return embedding

    embeddings = getattr(result, "embeddings", None)
    if embeddings:
        first = embeddings[0]
        values = getattr(first, "values", None)
        if values is not None:
            return values

    return None


def embed_text(text, task_type, title=None):
    if not text or not text.strip() or genai is None:
        return None

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    genai.configure(api_key=api_key)
    compact_text = text.strip()[:8000]

    attempts = [
        {
            "model": "models/text-embedding-004",
            "content": compact_text,
            "task_type": task_type,
            "title": title,
        },
        {
            "model": "models/embedding-001",
            "content": compact_text,
        },
    ]

    for kwargs in attempts:
        try:
            values = _extract_embedding_values(genai.embed_content(**kwargs))
            if values:
                return [float(value) for value in values]
        except Exception:
            continue

    return None


def vector_literal(values):
    if not values:
        return None
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"
