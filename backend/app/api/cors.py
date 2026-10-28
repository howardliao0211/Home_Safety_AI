from starlette.middleware.cors import CORSMiddleware


class ConfiguredCORS:
    """Resolve CORS after lifespan loads Settings; never allow arbitrary origins."""

    def __init__(self, app):
        self.app = app
        self.middleware = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if self.middleware is None:
            settings = scope["app"].state.settings
            self.middleware = CORSMiddleware(
                self.app,
                allow_origins=settings.cors_origins,
                allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                allow_headers=["Authorization", "X-Device-ID", "X-Deletion-Receipt", "Content-Type"],
                expose_headers=["X-Request-ID"],
            )
        return await self.middleware(scope, receive, send)
