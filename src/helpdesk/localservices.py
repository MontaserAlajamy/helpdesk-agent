"""Real local endpoints for check_service, used by the evals and by the public demo.

intranet answers HTTP 200, pbx and mail accept TCP. A service listed as down points at a closed port instead,
so check_service does a real network check and really fails.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any


class LocalServices:
    """Async context manager: `async with LocalServices() as services` gives {name: url} for three live services."""

    names = ("intranet", "pbx", "mail")

    async def __aenter__(self) -> dict[str, str]:
        async def http_ok(reader, writer):
            await reader.read(1024)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
            writer.close()

        async def tcp_ok(reader, writer):
            writer.close()

        self.http = await asyncio.start_server(http_ok, "127.0.0.1", 0)
        self.tcp = await asyncio.start_server(tcp_ok, "127.0.0.1", 0)
        closed = await asyncio.start_server(tcp_ok, "127.0.0.1", 0)
        closed_port = closed.sockets[0].getsockname()[1]
        closed.close()
        await closed.wait_closed()
        self.down_url = f"tcp://127.0.0.1:{closed_port}"
        tcp_url = f"tcp://127.0.0.1:{self.tcp.sockets[0].getsockname()[1]}"
        return {
            "intranet": f"http://127.0.0.1:{self.http.sockets[0].getsockname()[1]}/healthz",
            "pbx": tcp_url,
            "mail": tcp_url,
        }

    def with_down(self, services: dict[str, str], down: Iterable[str]) -> dict[str, str]:
        """A copy of `services` where every name in `down` points at the closed port. Unknown names are ignored."""
        down = set(down)
        return {name: (self.down_url if name in down else url) for name, url in services.items()}

    def for_task(self, services: dict[str, str], task: dict[str, Any]) -> dict[str, str]:
        return self.with_down(services, task.get("down", []))

    async def __aexit__(self, *exc) -> None:
        for srv in (self.http, self.tcp):
            srv.close()
            await srv.wait_closed()
