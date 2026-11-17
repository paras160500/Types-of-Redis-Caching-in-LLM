import os
import time
from redisvl.extensions.cache.embeddings import EmbeddingsCache
from redisvl.utils.vectorize import HFTextVectorizer

os.environ["TOKENIZERS_PARALLELISM"] = "False"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

print("Loading local embedding model...")
# 1. Initialize RedisVL EmbeddingsCache
embed_cache = EmbeddingsCache(
    name="embed_demo",
    redis_url="redis://localhost:6379",
    ttl=3600,  # Keep vectors cached for 1 hour
)

# 2. Attach the cache directly to the vectorizer
vectorizer = HFTextVectorizer(model=MODEL_NAME, cache=embed_cache)


def get_embedding_with_stats(raw_prompt: str):
    # Normalize text so casing/whitespace variations share the same cached vector
    normalized_prompt = raw_prompt.lower().strip()

    start_time = time.perf_counter()

    # Check if this text + model is already cached in Redis
    is_hit = embed_cache.exists(content=normalized_prompt, model_name=MODEL_NAME)

    # vectorizer.embed() automatically reads from / writes to embed_cache
    vector = vectorizer.embed(normalized_prompt)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    status = "✅ EMBEDDING CACHE HIT" if is_hit else "❌ EMBEDDING CACHE MISS (Computed & Saved)"
    print(f"\n{status} ({elapsed_ms:.2f} ms)")
    print(f"   Normalized text : '{normalized_prompt}'")
    print(f"   Vector dims     : {len(vector)}")
    print(f"   First 5 values  : {[round(x, 4) for x in vector[:5]]}")


if __name__ == "__main__":
    print("\n=== Project 4: Embedding Cache (No LLM Needed) ===")
    print("Type 'clear' to wipe cached vectors, or 'exit' to quit.\n")
    print("💡 Try asking: 'What is Kubernetes?'")
    print("   Then ask:   '  WHAT IS KUBERNETES?  '")

    while True:
        user_prompt = input("\nText to embed: ").strip()
        if user_prompt.lower() in {"exit", "quit"}:
            break
        if user_prompt.lower() == "clear":
            embed_cache.clear()
            print("🧹 Embedding cache cleared!")
            continue
        if user_prompt:
            get_embedding_with_stats(user_prompt)