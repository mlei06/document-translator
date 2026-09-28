"""A local fake of the OpenAI-compatible chat completions API for end-to-end tests.

Serves ``POST /v1/chat/completions`` on 127.0.0.1 and answers with ``fake_translation`` of every
segment, so the real LLM engine (HTTP, JSON parsing, batching, error mapping) runs without the
company server. ``status`` forces an HTTP error status for failure tests.
"""

import json
import re
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from doctranslator_core.types import LANGUAGE_NAMES, Language
from support.fakes import fake_translation

__all__ = ["FakeLlm", "fake_llm_server"]

_TARGET = re.compile(r"to ([A-Za-z ]+?)\.")


@dataclass
class FakeLlm:
    base_url: str
    status: int = 200
    requests: list[list[str]] = field(default_factory=list[list[str]])


@contextmanager
def fake_llm_server() -> Generator[FakeLlm]:
    state = FakeLlm(base_url="")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if state.status != 200:
                self._send(state.status, {"error": "forced"})
                return
            system, user = body["messages"][0]["content"], body["messages"][1]["content"]
            segments: list[str] = json.loads(user)["segments"]
            state.requests.append(segments)
            name = _TARGET.search(system)
            target = next(
                (lang for lang, full in LANGUAGE_NAMES.items() if name and full == name.group(1)),
                Language.EN,
            )
            content = json.dumps(
                {"translations": [fake_translation(s, target) for s in segments]},
                ensure_ascii=False,
            )
            self._send(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})

        def _send(self, status: int, payload: object) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
