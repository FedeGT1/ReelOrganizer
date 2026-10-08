from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

PUBLIC_PATHS = {"/login", "/health"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith("/static/"):
            return await call_next(request)

        if request.session.get("user_id"):
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        if request.headers.get("HX-Request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": "/login"})

        return RedirectResponse(url="/login", status_code=307)
