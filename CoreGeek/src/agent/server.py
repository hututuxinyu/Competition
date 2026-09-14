import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .brain import decide
from .protocol import Response

LOGGER = logging.getLogger(__name__)

_EMPTY_BODY = b'{"roleCommandMap":{},"prompt":"","executeCmd":""}'


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            response = decide(payload)
            body = json.dumps(response.to_dict(), ensure_ascii=False).encode("utf-8")
            LOGGER.info(
                "round %s -> %d cmds, prompt=%dB, cmd=%dB",
                payload.get("roundNo"),
                len(response.role_command_map),
                len(response.prompt),
                len(response.execute_cmd),
            )
        except Exception:
            LOGGER.exception("decision failed, returning empty response")
            body = _EMPTY_BODY
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(port: int) -> None:
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
