import os

from agent_framework.openai import OpenAIChatClient


def build_chat_client() -> tuple[OpenAIChatClient, str, str]:
    provider = os.getenv("LLM_PROVIDER", "github").strip().lower()

    if provider == "github":
        github_token = os.getenv("GITHUB_MODELS_TOKEN", "")
        github_model = os.getenv("GITHUB_MODELS_MODEL", "openai/gpt-4.1")

        if not github_token:
            raise RuntimeError("GITHUB_MODELS_TOKEN is required when LLM_PROVIDER=github")

        return (
            OpenAIChatClient(
                api_key=github_token,
                model_id=github_model,
                base_url="https://models.github.ai/inference",
                default_headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": os.getenv("GITHUB_MODELS_API_VERSION", "2022-11-28"),
                },
            ),
            "github",
            github_model,
        )

    if provider == "openai":
        openai_api_key = os.getenv("OPENAI_API_KEY", "")
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        if not openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        return (
            OpenAIChatClient(
                api_key=openai_api_key,
                model_id=openai_model,
                base_url=openai_base_url,
            ),
            "openai",
            openai_model,
        )

    raise RuntimeError("LLM_PROVIDER must be either 'github' or 'openai'")
