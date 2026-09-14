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
            _log_round(payload, response)
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


def _log_round(payload: dict[str, Any], response: Response) -> None:
    """增强日志：回合摘要 + 命令详情 + 0-cmd 标记，便于事后追溯。"""
    round_no = payload.get("roundNo")
    team = payload.get("teamOur") or {}
    roles = team.get("roles") or []
    station = next((r for r in roles if r.get("roleType") == "station"), {})
    robots = (payload.get("robot") or {}).get("roles") or []
    cmd_count = len(response.role_command_map)
    LOGGER.info(
        "round %s | gold=%s score=%s base_hp=%s | ours=%d robots=%d | "
        "cmds=%d prompt=%dB executeCmd=%dB",
        round_no, team.get("goldNum"), team.get("totalScore"),
        station.get("health"), len(roles), len(robots),
        cmd_count, len(response.prompt), len(response.execute_cmd),
    )
    if cmd_count == 0:
        LOGGER.warning("round %s [0-CMD] no command produced (check plan logic)", round_no)
    for rid, cmd in response.role_command_map.items():
        LOGGER.info("  R%s: %s", rid, json.dumps(cmd, ensure_ascii=False))


def serve(port: int) -> None:
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
