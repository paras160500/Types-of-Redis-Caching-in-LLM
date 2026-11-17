import os
import time
from dotenv import load_dotenv
from groq import Groq
from redisvl.extensions.cache.llm import SemanticCache
from redisvl.utils.vectorize import HFTextVectorizer

load_dotenv()
os.environ["TOKENIZERS_PARALLELISM"] = "False"

llm = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-20b"
vectorizer = HFTextVectorizer(model="sentence-transformers/all-MiniLM-L6-v2")

# SemanticCache stores both normal answers and negative (refusal) responses
cache = SemanticCache(
    name="negative_cache_demo",
    redis_url="redis://localhost:6379",
    distance_threshold=0.25,
    vectorizer=vectorizer,
    ttl=3600,
)

REFUSAL_PREFIX = "REFUSAL:"
SYSTEM_PROMPT = (
    "You are a strict Redis & AI Caching tutor. "
    "ONLY answer questions about Redis, databases, or AI caching. "
    "If the user asks about ANY other topic (like cooking, sports, movies, or general trivia), "
    f"you MUST reply starting with '{REFUSAL_PREFIX}' followed by a polite 1-sentence refusal."
)


def ask_scoped_tutor(prompt: str):
    t0 = time.perf_counter()

    # 1. Check Semantic Cache first (catches both valid answers AND cached refusals)
    hits = cache.check(prompt=prompt, num_results=1)
    if hits:
        ms = (time.perf_counter() - t0) * 1000
        meta = hits[0].get("metadata") or {}
        response = hits[0]["response"]

        if meta.get("type") == "negative_refusal":
            print(f"\n🛑 NEGATIVE CACHE HIT ({ms:.1f} ms) | Known off-topic / unanswerable")
            print(f"   Matched rejected prompt: '{hits[0]['prompt']}'")
            print(f"Bot: {response}")
        else:
            print(f"\n✅ POSITIVE CACHE HIT ({ms:.1f} ms) | Valid in-scope answer")
            print(f"Bot: {response}")
        return

    # 2. Cache Miss -> Call the LLM
    print("\n❌ CACHE MISS | Calling LLM to evaluate scope...")
    completion = llm.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    raw_reply = completion.choices[0].message.content.strip()
    ms = (time.perf_counter() - t0) * 1000

    # 3. Check if the LLM refused the off-topic prompt
    if raw_reply.startswith(REFUSAL_PREFIX):
        clean_refusal = raw_reply.replace(REFUSAL_PREFIX, "", 1).strip()
        # Store as a Negative Cache entry with a shorter TTL (e.g., 5 mins)
        cache.store(
            prompt=prompt,
            response=clean_refusal,
            metadata={"type": "negative_refusal"},
            ttl=300,
        )
        print(f"💾 SAVED TO NEGATIVE CACHE ({ms:.1f} ms) | Will block similar off-topic prompts for 5m")
        print(f"Bot: {clean_refusal}")
    else:
        # Store as a normal Positive Cache entry (1 hour TTL)
        cache.store(
            prompt=prompt,
            response=raw_reply,
            metadata={"type": "positive_answer"},
            ttl=3600,
        )
        print(f"💾 SAVED TO POSITIVE CACHE ({ms:.1f} ms)")
        print(f"Bot: {raw_reply}")


if __name__ == "__main__":
    print("=== Project 7: Negative Cache (Scoped Tutor Bot) ===")
    print("Type 'clear' to wipe cache, or 'exit' to quit.\n")
    print("💡 Demo Flow:")
    print("   1. Ask off-topic: 'What is a good pizza recipe?'     -> LLM refuses & saves to Negative Cache")
    print("   2. Ask similar  : 'How do I make pepperoni pizza?'   -> Negative Cache HIT! (0 LLM tokens wasted)")
    print("   3. Ask in-scope : 'What is a semantic cache?'        -> LLM answers & saves to Positive Cache")
    print("   4. Ask in-scope : 'Explain semantic caching'         -> Positive Cache HIT!")

    while True:
        q = input("\nYou: ").strip()
        if q.lower() in {"exit", "quit"}:
            break
        if q.lower() == "clear":
            cache.clear()
            print("🧹 Cache cleared!")
            continue
        if q:
            ask_scoped_tutor(q)