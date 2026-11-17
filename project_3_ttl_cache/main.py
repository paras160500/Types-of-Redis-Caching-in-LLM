import hashlib
import os
import time
import redis
from dotenv import load_dotenv
from groq import Groq

# Load GROQ_API_KEY from .env
load_dotenv()

cache = redis.Redis(host="localhost", port=6379, decode_responses=True)
llm = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-20b"

# Set a short TTL of 20 seconds so you can watch it expire live
TTL_SECONDS = 20


def make_cache_key(prompt: str) -> str:
    # Normalize lowercase/spaces so minor casing differences still hit
    normalized = prompt.lower().strip()
    prompt_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"ttl:{prompt_hash}"


def ask_agent(prompt: str):
    start_time = time.perf_counter()
    key = make_cache_key(prompt)

    # 1. Check Redis first
    cached_response = cache.get(key)
    if cached_response:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        # Check how many seconds remain before Redis deletes this key
        seconds_left = cache.ttl(key)

        print(f"\n✅ CACHE HIT ({elapsed_ms:.1f} ms) | ⏳ Expires in: {seconds_left}s")
        print(f"Answer: {cached_response}")
        return

    # 2. Cache Miss (either never asked, or previous TTL expired)
    print("\n❌ CACHE MISS (Not found or expired) | Calling LLM...")
    completion = llm.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Give concise, 2-sentence answers."},
            {"role": "user", "content": prompt},
        ],
    )
    answer = completion.choices[0].message.content

    # 3. Save in Redis WITH an expiration timer (ex=TTL_SECONDS)
    cache.set(key, answer, ex=TTL_SECONDS)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    print(f"💾 SAVED WITH {TTL_SECONDS}s TTL ({elapsed_ms:.1f} ms)")
    print(f"Answer: {answer}")


if __name__ == "__main__":
    print(f"=== Project 3: TTL Cache (Auto-Expires in {TTL_SECONDS}s) ===")
    print("Type a prompt (or 'exit' to quit).\n")
    print("💡 Demo Flow:")
    print("   1. Ask 'What is Redis?' -> Cache Miss (sets 20s timer)")
    print("   2. Ask again immediately -> Cache Hit (watch the countdown)")
    print("   3. Wait 20 seconds and ask again -> Cache Miss (auto-expired!)")

    while True:
        user_prompt = input("\nYou: ").strip()
        if user_prompt.lower() in {"exit", "quit"}:
            break
        if user_prompt:
            ask_agent(user_prompt)