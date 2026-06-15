from openai import OpenAI
from src.config import ACTIVE_MODEL, MODEL_MODE

def test_connection():
    print(f"Mode: {MODEL_MODE}")
    print(f"Model: {ACTIVE_MODEL['model']}")

    client = OpenAI(
        api_key=ACTIVE_MODEL["api_key"],
        base_url=ACTIVE_MODEL["base_url"],
    )

    response = client.chat.completions.create(
        model=ACTIVE_MODEL["model"],
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with: connection successful"}],
    )

    print(f"Response: {response.choices[0].message.content}")
    print("API connection OK")

if __name__ == "__main__":
    test_connection()
