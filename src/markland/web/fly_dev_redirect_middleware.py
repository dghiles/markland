from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse


class FlyDevRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        host = request.headers.get("host", "").lower()
        if host == "markland.fly.dev":
            target = f"https://markland.dev{request.url.path}"
            if request.url.query:
                target = f"{target}?{request.url.query}"
            return RedirectResponse(target, status_code=301)
        return await call_next(request)
