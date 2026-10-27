import logging
from contextlib import ExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.cors import ConfiguredCORS
from app.api.routes import router
from app.assessments.service import AssessmentService
from app.config import Settings
from app.errors import AppError
from app.models.providers.factory import build_provider
from app.models.schemas import new_id
from app.storage.photos import GCSPhotoStore
from app.storage.repository import FirestoreRepository

logger = logging.getLogger(__name__)


def create_app(settings=None, repository=None, photos=None, provider=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings()
        if config.environment == "production":
            # Configuration is resolved at startup, including env-file settings.
            # Remove the actual routes, not just their OpenAPI visibility.
            documentation_paths = {
                app.docs_url,
                app.redoc_url,
                app.openapi_url,
                "/docs/oauth2-redirect",
            }
            app.router.routes[:] = [
                route
                for route in app.router.routes
                if getattr(route, "path", None) not in documentation_paths
            ]
            app.docs_url = app.redoc_url = app.openapi_url = None
        with ExitStack() as stack:
            model = provider or build_provider(config)
            stack.callback(model.close)
            records = repository or FirestoreRepository(config)
            stack.callback(records.close)
            images = photos or GCSPhotoStore(config)
            stack.callback(images.close)
            app.state.settings = config
            app.state.service = AssessmentService(records, images, model)
            yield

    app = FastAPI(title="Home Safety AI", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = new_id()
        try:
            response = await call_next(request)
        except Exception as exc:
            # Catch before ServerErrorMiddleware re-raises to the ASGI server: SDK
            # exception bodies may include private payloads and must not be logged there.
            logger.error(
                "request_failed request_id=%s exception_type=%s",
                request.state.request_id,
                type(exc).__name__,
            )
            response = JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "service_unavailable",
                        "message": "Storage is unavailable. Retry the same operation.",
                        "request_id": request.state.request_id,
                    }
                },
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AppError)
    async def known_error(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Request fields are invalid. Check the API field types and required values.",
                    "fields": [".".join(str(part) for part in e["loc"]) for e in exc.errors()],
                    "request_id": request.state.request_id,
                }
            },
        )

    app.include_router(router)
    app.add_middleware(ConfiguredCORS)
    return app


app = create_app()
