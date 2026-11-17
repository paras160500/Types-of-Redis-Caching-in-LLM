import hashlib
import os 
import time 
import redis 
from dotenv import load_dotenv
from groq import Groq 

load_dotenv()

cache = redis.Redis(host = "localhost" , port = 6379 , decode_responses=True)
llm = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"

def make_cache_key(prompt : str) -> str:
    """
        Turn any prompt into a fixed length sha-256 redis key
    """
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return f"exact:{prompt_hash}"

def ask_agent(prompt : str):
    start_time = time.perf_counter()
    key = make_cache_key(prompt)

    # Check redis first
    cached_response = cache.get(key)
    if cached_response:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        print(f"\n✔️ CACHE HIT ({elapsed_ms:.1f}ms) | Key {key[:20]}")
        print(f"Answer : {cached_response}")
        return 

    # Cache miss -> call the llm 
    print(f"\n❌ CACHE MISS | Calling LLM")
    completion = llm.chat.completions.create(
        model = MODEL , 
        messages = [
            {"role" : "system" , "content" : "Give concise, 2 sentense answers."},
            {"role" : "user" , "content" : prompt}
        ]
    )

    answer = completion.choices[0].message.content 

    cache.set(key , answer)

    elapsed_ms = (time.perf_counter() - start_time) * 1000 
    print(f"Saved to Cache ({elapsed_ms : .1f}ms) | Key : {key[:20]}...")
    print(f"Answer : {answer}")


if __name__ == "__main__":
    print("====== Exact Match Cache =======")
    print("Type a prompt (or exit to quit)")
    print("Tip : Ask what is kubernets? for two times second time you will see magic")

    while True:
        user_prompt = input("\nYou : ").strip()
        if user_prompt.lower() in {"exit" , "quit"}:
            break 
        if user_prompt:
            ask_agent(user_prompt)