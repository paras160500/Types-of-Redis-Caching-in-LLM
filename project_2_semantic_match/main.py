import os
import time
from dotenv import load_dotenv
from groq import Groq
from redisvl.extensions.cache.llm import SemanticCache
from redisvl.utils.vectorize import HFTextVectorizer

# Load GROQ_API_KEY from .env
load_dotenv()

os.environ["TOKENIZERS_PARALLELISM"] = "False"
llm = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-20b"

print("Loading local embedding model (downloads ~90MB on first run)...")
vectorizer = HFTextVectorizer(model="sentence-transformers/all-MiniLM-L6-v2")

# Initialize Redis Semantic Cache
# distance_threshold: 0.0 = exact match, 1.0 = loosely related. 0.25 is a great sweet spot.
semantic_cache = SemanticCache(
    name="semantic_demo",
    redis_url="redis://localhost:6379",
    distance_threshold=0.25,
    vectorizer=vectorizer,
)


def ask_agent(prompt: str):
    start_time = time.perf_counter()

    # 1. Check Semantic Cache by meaning
    hits = semantic_cache.check(prompt=prompt, num_results=1)
    if hits:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        matched_prompt = hits[0]["prompt"]
        distance = hits[0]["vector_distance"]
        answer = hits[0]["response"]

        print(f"\n✅ SEMANTIC HIT ({elapsed_ms:.1f} ms)")
        print(f"   Matched stored prompt: '{matched_prompt}' (distance: {distance:.3f})")
        print(f"Answer: {answer}")
        return

    # 2. Cache Miss -> Call the LLM
    print("\n❌ CACHE MISS | Calling LLM...")
    completion = llm.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Give concise, 2-sentence answers."},
            {"role": "user", "content": prompt},
        ],
    )
    answer = completion.choices[0].message.content

    # 3. Store prompt + vector + answer in Redis
    semantic_cache.store(prompt=prompt, response=answer)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    print(f"💾 SAVED TO SEMANTIC CACHE ({elapsed_ms:.1f} ms)")
    print(f"Answer: {answer}")


if __name__ == "__main__":
    print("\n=== Project 2: Semantic Cache ===")
    print("Type 'clear' to wipe cache, or 'exit' to quit.\n")
    print("💡 Try asking: 'What is Machine Learning?'")
    print("   Then ask:   'Can you explain how ML works?'")

    while True:
        user_prompt = input("\nYou: ").strip()
        if user_prompt.lower() in {"exit", "quit"}:
            break
        if user_prompt.lower() == "clear":
            semantic_cache.clear()
            print("🧹 Semantic cache cleared!")
            continue
        if user_prompt:
            ask_agent(user_prompt)