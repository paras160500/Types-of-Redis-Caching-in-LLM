import json
import os
import time
import redis
import requests
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

cache = redis.Redis(host="localhost", port=6379, decode_responses=True)
llm = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-20b"
WEATHER_TTL_SECONDS = 600  # Cache external weather API calls for 10 minutes


def get_weather(city: str) -> str:
    """Fetch live weather from Open-Meteo (free, no API key), wrapped with a Redis Tool Cache."""
    normalized_city = city.lower().strip()
    cache_key = f"tool:weather:{normalized_city}"

    # 1. Check Tool Cache first
    cached_data = cache.get(cache_key)
    if cached_data:
        ttl_left = cache.ttl(cache_key)
        print(f"   ⚡ TOOL CACHE HIT for '{city}' (TTL remaining: {ttl_left}s) -> Skipped Open-Meteo API!")
        return cached_data

    # 2. Tool Cache Miss -> Call Open-Meteo Geocoding + Weather API
    print(f"   🌐 TOOL CACHE MISS for '{city}' -> Calling live Open-Meteo API...")
    geo_res = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=10,
    ).json()

    if not geo_res.get("results"):
        return json.dumps({"error": f"City '{city}' not found"})

    loc = geo_res["results"][0]
    weather_res = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
            "current": "temperature_2m,wind_speed_10m",
        },
        timeout=10,
    ).json()

    result_payload = json.dumps({
        "city": loc["name"],
        "country": loc.get("country", ""),
        "temperature_c": weather_res["current"]["temperature_2m"],
        "wind_speed_kmh": weather_res["current"]["wind_speed_10m"],
    })

    # 3. Store the raw tool output in Redis with a 10-minute TTL
    cache.set(cache_key, result_payload, ex=WEATHER_TTL_SECONDS)
    return result_payload


# Define the tool schema for Groq
WEATHER_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current live temperature and wind speed for a given city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name, e.g. Delhi, Tokyo, London"}
                },
                "required": ["city"],
            },
        },
    }
]


def ask_weather_agent(user_prompt: str):
    t0 = time.perf_counter()
    messages = [
        {"role": "system", "content": "You are a concise weather assistant. Use get_weather when asked about weather."},
        {"role": "user", "content": user_prompt},
    ]

    # Step 1: Ask LLM (it will decide whether to call get_weather)
    response = llm.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=WEATHER_TOOL,
        tool_choice="auto",
    )
    msg = response.choices[0].message

    # Step 2: Execute requested tool calls (using our Redis-cached get_weather)
    if msg.tool_calls:
        messages.append(msg)
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            tool_output = get_weather(city=args["city"])
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": tool_output,
            })

        # Step 3: Send tool result back to LLM for final natural-language answer
        final = llm.chat.completions.create(model=MODEL, messages=messages)
        answer = final.choices[0].message.content
    else:
        answer = msg.content

    ms = (time.perf_counter() - t0) * 1000
    print(f"🤖 Agent ({ms:.0f} ms): {answer}")


if __name__ == "__main__":
    print("=== Project 6B: Tool / Function-Call Cache ===")
    print("Type 'exit' to quit.\n")
    print("💡 Demo Flow:")
    print("   1. Ask: 'What is the weather in Delhi?'          -> Tool Cache Miss (calls Open-Meteo)")
    print("   2. Ask: 'Should I wear a jacket in Delhi today?' -> Tool Cache Hit! (reuses weather JSON)")

    while True:
        q = input("\nYou: ").strip()
        if q.lower() in {"exit", "quit"}:
            break
        if q:
            ask_weather_agent(q)