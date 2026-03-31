import os

def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def get_openai_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    return api_key


def get_openai_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
