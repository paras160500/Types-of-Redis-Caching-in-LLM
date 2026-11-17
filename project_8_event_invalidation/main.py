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

# 1. Initialize SemanticCache with a 'product_id' tag so we can selectively invalidate entries
price_cache = SemanticCache(
    name="product_price_cache",
    redis_url="redis://localhost:6379",
    distance_threshold=0.25,
    vectorizer=vectorizer,
    filterable_fields=[{"name": "product_id", "type": "tag"}],
    ttl=86400,  # Long 24-hour TTL because invalidation is handled by events, not timers!
)

# Simulated live product database (Source of Truth)
PRODUCT_DB = {
    "widget_a": {"name": "Widget A", "price": 10.00, "stock": "In Stock"},
    "widget_b": {"name": "Widget B", "price": 25.00, "stock": "In Stock"},
}


def detect_product_id(prompt: str) -> str:
    """Simple helper to identify which product the user is asking about."""
    p = prompt.lower()
    if "widget b" in p:
        return "widget_b"
    return "widget_a"


def ask_product_agent(prompt: str):
    t0 = time.perf_counter()
    product_id = detect_product_id(prompt)
    product_filter = Tag("product_id") == product_id

    # 2. Check SemanticCache scoped to this product_id
    hits = price_cache.check(prompt=prompt, filter_expression=product_filter, num_results=1)
    if hits:
        ms = (time.perf_counter() - t0) * 1000
        print(f"\n✅ CACHE HIT ({ms:.1f} ms) | Tag: product_id={product_id}")
        print(f"Bot: {hits[0]['response']}")
        return

    # 3. Cache Miss -> Read live DB & call LLM
    item = PRODUCT_DB[product_id]
    print(f"\n❌ CACHE MISS | Reading live DB ({item['name']}: ${item['price']:.2f}) & calling LLM...")

    completion = llm.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    f"Answer in 1 concise sentence using this live product data: "
                    f"{item['name']} costs ${item['price']:.2f} and is {item['stock']}."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    answer = completion.choices[0].message.content

    # 4. Store in cache tagged with product_id so we can invalidate it later
    price_cache.store(
        prompt=prompt,
        response=answer,
        filters={"product_id": product_id},
    )

    ms = (time.perf_counter() - t0) * 1000
    print(f"💾 SAVED TO CACHE ({ms:.1f} ms) | Tagged with product_id='{product_id}'")
    print(f"Bot: {answer}")


def update_product_price(product_id: str, new_price: float):
    """Update the database AND immediately invalidate only the affected cache entries."""
    old_price = PRODUCT_DB[product_id]["price"]
    PRODUCT_DB[product_id]["price"] = new_price

    # Event-Driven Invalidation: find & delete every cached answer tagged with this product_id
    result = price_cache._index.drop_by_filter(Tag("product_id") == product_id)

    print(f"\n🔔 EVENT: {PRODUCT_DB[product_id]['name']} price updated: ${old_price:.2f} -> ${new_price:.2f}")
    print(f"🧹 Invalidated {result.processed} stale cached answer(s) for '{product_id}' immediately!")


if __name__ == "__main__":
    print("=== Project 8: Event-Driven Cache Invalidation ===")
    price_cache.clear()
    print("Commands:")
    print("  • Ask a question, e.g. 'What is the price of Widget A?'")
    print("  • Type 'update a 20' to change Widget A's price to $20.00 (triggers invalidation)")
    print("  • Type 'exit' to quit\n")

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break

        # Command to simulate a database price-change event: "update a 20" or "update b 35"
        if user_input.lower().startswith("update "):
            parts = user_input.split()
            if len(parts) == 3 and parts[1].lower() in {"a", "b"}:
                pid = f"widget_{parts[1].lower()}"
                try:
                    update_product_price(pid, float(parts[2]))
                except ValueError:
                    print("Usage: update a 20.00")
                continue

        if user_input:
            ask_product_agent(user_input)