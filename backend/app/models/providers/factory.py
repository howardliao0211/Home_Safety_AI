from app.config import Settings
from app.models.providers.base import ModelProvider
from app.models.providers.groq import GroqProvider
from app.models.providers.muse import MuseProvider


def build_provider(settings: Settings) -> ModelProvider:
    if settings.model_provider == "groq":
        return GroqProvider(settings)
    return MuseProvider(settings)
