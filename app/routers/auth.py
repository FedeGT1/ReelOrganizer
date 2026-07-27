from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.auth import get_client_ip, rate_limiter, verify_credentials
from app.web import templates

router = APIRouter(tags=["auth"])


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    client_ip = get_client_ip(request)

    if rate_limiter.is_locked_out(client_ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Troppi tentativi falliti. Riprova tra qualche minuto."},
            status_code=429,
        )

    if verify_credentials(username, password):
        rate_limiter.reset(client_ip)
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=303)

    rate_limiter.record_failure(client_ip)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Credenziali non valide."},
        status_code=401,
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
