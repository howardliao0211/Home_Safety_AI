from app.config import Settings
from app.models.providers.base import ModelProvider
from app.models.providers.groq import GroqProvider


def build_provider(settings: Settings) -> ModelProvider:
    if settings.model_provider == "groq":
        return GroqProvider(settings)
    raise RuntimeError(
        "Muse integration is pending the organisers' API contract. "
        "Implement a ModelProvider adapter and register it in build_provider; "
        "use MODEL_PROVIDER=groq for development. No fallback was attempted."
    )
