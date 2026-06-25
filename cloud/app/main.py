from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cloud.app.api.qqbot_routes import router as qqbot_router
from cloud.app.api.routes import router
from cloud.app.api.web_routes import router as web_router
from cloud.app.automation_tasks import get_automation_task_service
from cloud.app.config import get_settings
from cloud.app.device_state.store import device_state_store
from cloud.app.mqtt_service.subscriber import MqttStateSubscriber
from cloud.app.qqbot_gateway import QQBotGatewayService
from cloud.app.security import ApiRateLimiter, extract_client_ip


api_rate_limiter = ApiRateLimiter()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    subscriber = MqttStateSubscriber(settings, device_state_store)
    qqbot_gateway = QQBotGatewayService(settings)
    automation_tasks = get_automation_task_service(settings)
    subscriber.start()
    qqbot_gateway.start()
    automation_tasks.start()
    try:
        yield
    finally:
        qqbot_gateway.stop()
        subscriber.stop()
        automation_tasks.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Embedded Agent Cloud", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        settings = get_settings()
        path = request.url.path
        if path not in {"/", "/health"} and not path.startswith("/assets/"):
            limit = settings.api_rate_limit_max_requests
            if path.startswith("/agent/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                limit = settings.api_deploy_rate_limit_max_requests
            key = f"{extract_client_ip(request)}:{request.method}:{path}"
            if not api_rate_limiter.allow(key, limit, settings.api_rate_limit_window_sec):
                return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})

        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    app.include_router(router)
    app.include_router(qqbot_router)
    app.include_router(web_router)
    # nginx strips /api in production; keep it locally so this SPA also works without nginx.
    app.include_router(web_router, prefix="/api", include_in_schema=False)
    web_dir = Path(__file__).resolve().parent.parent / "web"
    app.mount("/assets", StaticFiles(directory=web_dir), name="assets")

    def _web_index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/", include_in_schema=False)
    def web_index() -> FileResponse:
        return _web_index()

    @app.get("/console", include_in_schema=False)
    def web_console() -> FileResponse:
        return _web_index()

    @app.get("/nl-console", include_in_schema=False)
    def web_nl_console() -> FileResponse:
        return _web_index()

    return app


app = create_app()
