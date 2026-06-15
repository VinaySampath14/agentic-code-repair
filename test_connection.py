import anthropic
from src.config import ACTIVE_MODEL, MODEL_MODE

def test_connection():
    print(f"Mode: {MODEL_MODE}")
    print(f"Model: {ACTIVE_MODEL['model']}")

    client = anthropic.Anthropic(api_key=ACTIVE_MODEL["api_key"])

    message = client.messages.create(
        model=ACTIVE_MODEL["model"],
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with: connection successful"}],
    )

    print(f"Response: {message.content[0].text}")
    print("API connection OK")

if __name__ == "__main__":
    test_connection()
