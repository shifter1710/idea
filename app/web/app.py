from __future__ import annotations

from wsgiref.simple_server import make_server

from app.config import BASE_DIR, load_settings
from app.web.handlers import WebHandlers
from app.web.http import parse_request, respond_html
from app.web.presenter import ScalePresenter
from app.web.routes import WebRouter
from app.web.views import WebRenderer
from app.web_repository import ParsedScaleRepository
from app.web_service import WebScoringService


class WsgiApplication:
    def __init__(self, router: WebRouter) -> None:
        self.router = router

    def __call__(self, environ, start_response):
        request = parse_request(environ)
        status, html_text = self.router.dispatch(request)
        return respond_html(start_response, html_text, status=status)


def create_application() -> WsgiApplication:
    repository = ParsedScaleRepository(BASE_DIR)
    service = WebScoringService(repository)
    presenter = ScalePresenter(service)
    renderer = WebRenderer(presenter)
    handlers = WebHandlers(service, presenter, renderer)
    return WsgiApplication(WebRouter(handlers))


def run() -> None:
    settings = load_settings()
    application = create_application()
    with make_server(settings.web_host, settings.web_port, application) as server:
        print(f"Web UI started on http://{settings.web_host}:{settings.web_port}", flush=True)
        server.serve_forever()
