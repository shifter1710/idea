from __future__ import annotations

from app.web.handlers import WebHandlers
from app.web.http import RequestContext


class WebRouter:
    def __init__(self, handlers: WebHandlers) -> None:
        self.handlers = handlers

    def dispatch(self, request: RequestContext) -> tuple[str, str]:
        try:
            if request.path == "/":
                return "200 OK", self.handlers.home()
            if request.path == "/calculate":
                return "200 OK", self.handlers.calculator(request.query, request.form if request.method == "POST" else {})
            if request.path.startswith("/scale/"):
                return "200 OK", self.handlers.scale(int(request.path.rsplit("/", 1)[1]))
            return "404 Not Found", self.handlers.renderer.render_not_found()
        except ValueError as exc:
            return "400 Bad Request", self.handlers.renderer.render_message("Ошибка", str(exc))
        except LookupError as exc:
            return "404 Not Found", self.handlers.renderer.render_message("Не найдено", str(exc))
