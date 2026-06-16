import os
from dotenv import load_dotenv

load_dotenv()

MODEL_MODE = os.getenv("MODEL_MODE", "paid")
EVAL_MODE = os.getenv("EVAL_MODE", "false").lower() == "true"

MODEL_CONFIG = {
    "paid": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "api_key": os.getenv("OPENAI_API_KEY"),
    },
    "mini": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key": os.getenv("OPENAI_API_KEY"),
    },
    "local": {
        "base_url": "http://localhost:8000/v1",
        "model": "Qwen/Qwen2.5-Coder-32B-Instruct",
        "api_key": "none",
    },
}

ACTIVE_MODEL = MODEL_CONFIG[MODEL_MODE]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")

EXPLORER_MAX_FILES = 8
EXPLORER_MAX_ITERATIONS = 3
CODER_MAX_RETRIES = 3
FIX_SCORE_THRESHOLD = 0.6
