import os
import time
from dotenv import load_dotenv
from groq import Groq
from redisvl.extensions.cache.llm import SemanticCache
from redisvl.query.filter import Tag
from redisvl.utils.vectorize import HFTextVectorizer

load_dotenv()
os.environ["TOKENIZERS_PARALLELISM"] = "False"

llm = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-20b"
vectorizer = HFTextVectorizer(model="sentence-transformers/all-MiniLM-L6-v2")

# 1. Initialize SemanticCache with a 'user_id' tag for per-user segmentation
segmented_cache = SemanticCache(
    name="segmented_user_cache",
    redis_url="redis://localhost:6379",
    distance_threshold=0.25,
    vectorizer=vectorizer,
    filterable_fields=[{"name": "user_id", "type": "tag"}],
    ttl=3600,
)

# Simulated private user database
PRIVATE_USER_DB = {
    "alice": {"balance": "$14,250.00", "ticket": "Ticket #401 (Resolved)"},
    "bob": {"balance": "$320.50", "ticket": "Ticket #889 (In Progress)"},
    "carol": {"balance": "$89,100.00", "ticket": "Ticket #912 (Awaiting Reply)"},
}


def ask_account_agent(user_id: str, prompt: str, segment_per_user: bool):
    t0 = time.perf_counter()

    # 2. Build filter ONLY if segmentation is enabled
    user_filter = (Tag("user_id") == user_id) if segment_per_user else None

    # 3. Check SemanticCache
    hits = segmented_cache.check(prompt=prompt, filter_expression=user_filter, num_results=1)
    if hits:
        ms = (time.perf_counter() - t0) * 1000
        cached_owner = (hits[0].get("metadata") or {}).get("owner", "unknown")

        if cached_owner != user_id:
            print(f"\n⚠️  SECURITY LEAK! ({ms:.1f} ms) | {user_id.title()} received {cached_owner.title()}'s cached data!")
        else:
            print(f"\n✅ SAFE SEGMENTED HIT ({ms:.1f} ms) | Isolated to user '{user_id}'")

        print(f"Bot: {hits[0]['response']}")
        return

    # 4. Cache Miss -> Fetch this user's private records & call LLM
    user_data = PRIVATE_USER_DB[user_id]
    print(f"\n❌ CACHE MISS | Fetching private DB for '{user_id}' & calling LLM...")

    completion = llm.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a banking & support assistant speaking to {user_id.title()}. "
                    f"Their account balance is {user_data['balance']} and support status is {user_data['ticket']}. "
                    "Answer in 1 concise sentence."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    answer = completion.choices[0].message.content

    # 5. Store in Redis stamped with user_id filter + owner metadata
    segmented_cache.store(
        prompt=prompt,
        response=answer,
        filters={"user_id": user_id},
        metadata={"owner": user_id},
    )

    ms = (time.perf_counter() - t0) * 1000
    print(f"💾 SAVED TO CACHE ({ms:.1f} ms) | Segment: user_id='{user_id}'")
    print(f"Bot: {answer}")


if __name__ == "__main__":
    print("=== Project 9: Cache Segmentation (Tenant Isolation) ===")
    segmented_cache.clear()

    current_user = "alice"
    segment_enabled = False  # Start OFF to demonstrate the data leak first!

    print("\nCommands:")
    print("  • 'user alice' / 'user bob' / 'user carol' -> Switch active user")
    print("  • 'segment on' / 'segment off'             -> Toggle per-user cache isolation")
    print("  • 'clear'                                  -> Wipe cache")
    print("  • 'exit'                                   -> Quit")

    while True:
        mode_label = "ON (Safe)" if segment_enabled else "OFF (Unsafe - Shared)"
        raw = input(f"\n[User: {current_user.title()} | Segmentation: {mode_label}] Ask: ").strip()

        if raw.lower() in {"exit", "quit"}:
            break
        if raw.lower() == "clear":
            segmented_cache.clear()
            print("🧹 Cache cleared!")
            continue
        if raw.lower().startswith("user "):
            chosen = raw.split(maxsplit=1)[1].lower().strip()
            if chosen in PRIVATE_USER_DB:
                current_user = chosen
                print(f"🔄 Switched active user to: {current_user.title()}")
            else:
                print(f"Unknown user. Choose from: {', '.join(PRIVATE_USER_DB.keys())}")
            continue
        if raw.lower() in {"segment on", "segment off"}:
            segment_enabled = raw.lower() == "segment on"
            print(f"🔒 Cache segmentation is now {'ENABLED' if segment_enabled else 'DISABLED'}.")
            continue
        if raw:
            ask_account_agent(current_user, raw, segment_enabled)