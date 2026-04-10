from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs


@dataclass(frozen=True)
class RequestContext:
    method: str
    path: str
    query: dict[str, list[str]]
    form: dict[str, list[str]]


def parse_request(environ) -> RequestContext:
    method = environ["REQUEST_METHOD"].upper()
    query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    form = parse_form(environ) if method == "POST" else {}
    return RequestContext(method=method, path=environ.get("PATH_INFO", "/"), query=query, form=form)


def parse_form(environ) -> dict[str, list[str]]:
    size = int(environ.get("CONTENT_LENGTH", "0") or "0")
    raw_body = environ["wsgi.input"].read(size).decode("utf-8") if size else ""
    return parse_qs(raw_body, keep_blank_values=True)


def respond_html(start_response, html_text: str, status: str = "200 OK"):
    body = html_text.encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]
