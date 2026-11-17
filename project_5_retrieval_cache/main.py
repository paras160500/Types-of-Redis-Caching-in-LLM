import json
import os
import time
from dotenv import load_dotenv
from groq import Groq
from redisvl.extensions.cache.llm import SemanticCache
from redisvl.index import SearchIndex
from redisvl.query import VectorQuery
from redisvl.utils.vectorize import HFTextVectorizer

load_dotenv()
os.environ["TOKENIZERS_PARALLELISM"] = "False"

REDIS_URL = "redis://localhost:6379"
llm = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-20b"

print("Loading embedding model...")
vectorizer = HFTextVectorizer(model="sentence-transformers/all-MiniLM-L6-v2")

# 1. Define a mini Knowledge Base schema in Redis (384 dims for all-MiniLM-L6-v2)
kb_schema = {
    "index": {"name": "course_notes_idx", "prefix": "note", "storage_type": "hash"},
    "fields": [
        {"name": "topic", "type": "tag"},
        {"name": "content", "type": "text"},
        {
            "name": "embedding",
            "type": "vector",
            "attrs": {
                "dims": 384,
                "distance_metric": "cosine",
                "algorithm": "flat",
                "datatype": "float32",
            },
        },
    ],
}

# Sample course notes to populate our local vector DB
COURSE_NOTES = [
    {"topic": "exact", "content": "Exact Match Cache hashes prompts with SHA-256 for 1ms byte-for-byte lookups."},
    {"topic": "semantic", "content": "Semantic Cache uses vector embeddings and cosine distance to match paraphrased prompts."},
    {"topic": "ttl", "content": "TTL (Time-To-Live) sets an EXPIRE timer on Redis keys to automatically purge stale data."},
    {"topic": "embedding", "content": "Embedding Cache stores computed text vectors in Redis so identical texts aren't re-embedded."},
    {"topic": "retrieval", "content": "Retrieval Cache stores top-K vector search chunks so RAG pipelines skip repeated DB queries."},
]


def setup_knowledge_base() -> SearchIndex:
    """Create the RediSearch vector index and load our sample notes."""
    index = SearchIndex.from_dict(kb_schema, redis_url=REDIS_URL)
    index.create(overwrite=True)

    records = []
    for note in COURSE_NOTES:
        records.append({
            "topic": note["topic"],
            "content": note["content"],
            "embedding": vectorizer.embed(note["content"], as_buffer=True),
        })
    index.load(records)
    return index


vector_db = setup_knowledge_base()

# 2. Initialize Retrieval Cache (stores retrieved docs, NOT final LLM answers)
retrieval_cache = SemanticCache(
    name="retrieval_cache_demo",
    redis_url=REDIS_URL,
    distance_threshold=0.25,
    vectorizer=vectorizer,
    ttl=600,
)


def retrieve_documents(query: str, top_k: int = 2) -> list[str]:
    """Check Retrieval Cache first; if missed, run VectorQuery on RediSearch."""
    t0 = time.perf_counter()

    # Step A: Check Retrieval Cache
    cached = retrieval_cache.check(prompt=query, num_results=1)
    if cached:
        ms = (time.perf_counter() - t0) * 1000
        docs = json.loads(cached[0]["response"])
        print(f"   ✅ RETRIEVAL CACHE HIT ({ms:.1f} ms) -> Skipped Vector DB search!")
        return docs

    # Step B: Retrieval Cache Miss -> Embed query & run KNN search in Redis
    query_vec = vectorizer.embed(query, as_buffer=True)
    knn_query = VectorQuery(
        vector=query_vec,
        vector_field_name="embedding",
        return_fields=["content"],
        num_results=top_k,
    )
    results = vector_db.query(knn_query)
    docs = [row["content"] for row in results]

    # Step C: Store retrieved docs in Retrieval Cache for future queries
    retrieval_cache.store(prompt=query, response=json.dumps(docs))
    ms = (time.perf_counter() - t0) * 1000
    print(f"   ❌ RETRIEVAL CACHE MISS ({ms:.1f} ms) -> Searched Vector DB & cached {len(docs)} docs.")
    return docs


def rag_ask(user_prompt: str):
    print(f"\n🔍 Step 1: Fetching relevant context...")
    docs = retrieve_documents(user_prompt, top_k=2)
    for i, doc in enumerate(docs, 1):
        print(f"      Doc {i}: {doc}")

    print("🤖 Step 2: Sending cached/retrieved context + prompt to Groq LLM...")
    context_block = "\n".join(f"- {d}" for d in docs)
    completion = llm.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": f"Answer in 2 concise sentences using ONLY these notes:\n{context_block}",
            },
            {"role": "user", "content": user_prompt},
        ],
    )
    print(f"\nAnswer: {completion.choices[0].message.content}")


if __name__ == "__main__":
    print("\n=== Project 5: Retrieval Cache in RAG ===")
    print("Type 'clear' to wipe retrieval cache, or 'exit' to quit.\n")
    print("💡 Demo Flow:")
    print("   1. Ask: 'How does TTL prevent stale data?' -> Retrieval Miss (queries Vector DB)")
    print("   2. Ask: 'Explain TTL expiration in Redis'   -> Retrieval Hit! (skips Vector DB, still generates custom LLM answer)")

    while True:
        q = input("\nYou: ").strip()
        if q.lower() in {"exit", "quit"}:
            break
        if q.lower() == "clear":
            retrieval_cache.clear()
            print("🧹 Retrieval cache cleared!")
            continue
        if q:
            rag_ask(q)