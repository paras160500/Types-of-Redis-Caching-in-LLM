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

# ONE shared semantic cache across all users (no user_id in the key!)
shared_cache = SemanticCache(
    name="shared_faq_cache",
    redis_url="redis://localhost:6379",
    distance_threshold=0.25,
    vectorizer=vectorizer,
    ttl=3600,
)

# Simulated incoming traffic from different users
SIMULATED_TRAFFIC = [
    ("Alice", "What are the prerequisites for the AI Engineering course?"),
    ("Bob", "Do I need any prior experience before joining the AI Engineering course?"),
    ("Charlie", "How long does the AI Engineering course take to finish?"),
    ("Dana", "What is the duration of the AI Engineering program?"),
    ("Eve", "What should I know before taking the AI Engineering class?"),
]


def handle_user_request(user: str, prompt: str):
    t0 = time.perf_counter()
    hits = shared_cache.check(prompt=prompt, num_results=1)

    if hits:
        ms = (time.perf_counter() - t0) * 1000
        print(f"👤 [{user:7}] ✅ SHARED HIT  ({ms:5.1f} ms) | Q: '{prompt}'")
        print(f"             ↳ Reused answer: {hits[0]['response']}\n")
        return True

    # Cache Miss -> Call Groq LLM
    completion = llm.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful course FAQ assistant. Answer in 1 short sentence."},
            {"role": "user", "content": prompt},
        ],
    )
    answer = completion.choices[0].message.content
    shared_cache.store(prompt=prompt, response=answer)

    ms = (time.perf_counter() - t0) * 1000
    print(f"👤 [{user:7}] ❌ CACHE MISS  ({ms:5.1f} ms) | Q: '{prompt}'")
    print(f"             ↳ Generated & shared: {answer}\n")
    return False


if __name__ == "__main__":
    print("=== Project 6A: Multi-User Shared Cache ===\n")
    shared_cache.clear()

    total_hits = 0
    for user, question in SIMULATED_TRAFFIC:
        if handle_user_request(user, question):
            total_hits += 1

    print(f"📊 Summary: {total_hits}/{len(SIMULATED_TRAFFIC)} requests served from Shared Cache (0 LLM cost)!")