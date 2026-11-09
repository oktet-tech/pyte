# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""HTTP client session driven from the engine, executed on a test agent.

The requests themselves run on the agent: ``pyte.remote.python`` ships
the functions of :mod:`pyte.tools._http_ops` to the agent's python3 and
a cookie-keeping stdlib client lives there for the whole session. The
agent has only the Python standard library, which is why the client is
built on urllib and not on a third-party package.

The engine side (this module) validates arguments, ships one op per
request, turns results into :class:`Response` objects and logs: a step
bracket per request, the (truncated, redacted) bodies at RING and the
headers at VERB. Failures surface as :class:`pyte.errors.HttpError`.
"""
from __future__ import annotations

import base64
import json as jsonlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from pyte import log, remote
from pyte.errors import HttpError, RemotePythonError
from pyte.tools import _http_ops as _ops

TRANSPORT_MARGIN = 30.0
DEFAULT_LOG_BODY = 4096
MAX_BODY = 8 * 1024 * 1024
REDACTED = "<redacted>"
_ALWAYS_REDACT = frozenset({"authorization", "cookie", "set-cookie"})
_EXCERPT = 200


def _excerpt(text: str) -> str:
    return " ".join(text.split())[:_EXCERPT]


@dataclass(frozen=True)
class Response:
    """One HTTP response; header names are lower-cased."""

    status: int
    reason: str
    headers: dict[str, str]
    body: str
    url: str
    elapsed: float

    def json(self) -> Any:
        """Parse the body as JSON or raise HttpError."""
        try:
            return jsonlib.loads(self.body)
        except ValueError as exc:
            raise HttpError(f"{self.url}: body is not JSON: "
                            f"{_excerpt(self.body)}") from exc

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def _ship(rem, fn, label: str, *args, timeout: float | None = None,
          **kwargs):
    log.verb(f"http op: {label}")
    if timeout is not None:
        kwargs["timeout"] = timeout
    try:
        return rem.call(fn, *args, **kwargs)
    except RemotePythonError as exc:
        raise HttpError(f"{label}: {exc}") from exc


class Session:
    """A live HTTP client session on a test agent; see :func:`session`."""

    def __init__(self, rem, client, *, timeout: float, log_body: int,
                 redact: frozenset[str]):
        self._rem = rem
        self._client = client
        self._timeout = timeout
        self._log_body = log_body
        self._redact = _ALWAYS_REDACT | {x.lower() for x in redact}

    @property
    def remote(self):
        """The underlying pyte.remote session."""
        return self._rem

    def call(self, fn: Callable, *args, timeout: float | None = None,
             **kwargs):
        """Ship *fn* with the agent-side client as its first argument."""
        return self._ship(
            fn, f"call {fn.__name__}", self._client, *args,
            timeout=(timeout or self._timeout) + TRANSPORT_MARGIN, **kwargs)

    def _ship(self, fn, label: str, *args, timeout: float | None = None,
              **kwargs):
        """Log the op, ship it and wrap agent-side failures in HttpError.

        A transport timeout (pyte.errors.TimeoutError, a builtin
        TimeoutError) is not a RemotePythonError and propagates as is.
        """
        return _ship(self._rem, fn, label, *args, timeout=timeout, **kwargs)

    def _headers_line(self, headers: dict[str, str]) -> str:
        return ", ".join(
            f"{k}: {REDACTED if k.lower() in self._redact else v}"
            for k, v in headers.items())

    def _log_text(self, label: str, text: str, limit: int) -> None:
        if limit <= 0 or not text:
            return
        shown = text[:limit]
        if len(text) > limit:
            shown += f"... ({len(text)} chars)"
        log.ring(f"{label}: {shown}")

    def request(self, method: str, path: str, *, params=None, json=None,
                form=None, data=None, content_type: str | None = None,
                headers: dict[str, str] | None = None, ok: bool = True,
                timeout: float | None = None,
                log_body: int | None = None) -> Response:
        """Issue one request; with *ok* raise HttpError on non-2xx.

        At most one of json/form/data; data needs content_type. A str
        *data* is shipped as is, bytes are shipped base64-encoded
        (``data_b64``) and decoded on the agent.
        """
        if sum(x is not None for x in (json, form, data)) > 1:
            raise ValueError("json, form and data are mutually exclusive")
        if data is not None and content_type is None:
            raise ValueError("data requires content_type")
        limit = self._log_body if log_body is None else log_body
        agent_timeout = float(timeout or self._timeout)
        kw: dict[str, Any] = {"timeout": agent_timeout}
        if isinstance(data, (bytes, bytearray)):
            kw["data_b64"] = base64.b64encode(data).decode("ascii")
            data = None
        for key, val in (("params", params), ("json", json),
                         ("form", form), ("data", data),
                         ("content_type", content_type),
                         ("headers", headers)):
            if val is not None:
                kw[key] = val

        log.step_push(f"{method} {path}")
        popped = False
        try:
            if headers:
                log.verb(f"request headers: {self._headers_line(headers)}")
            if json is not None:
                self._log_text("request body", jsonlib.dumps(json), limit)
            elif form is not None:
                self._log_text("request body", repr(form), limit)
            elif isinstance(data, str):
                self._log_text("request body", data, limit)
            raw = self._ship(
                _ops.request, f"request {method} {path}", self._client,
                method, path, kw, timeout=agent_timeout + TRANSPORT_MARGIN)
            resp = Response(status=raw["status"], reason=raw["reason"],
                            headers=raw["headers"], body=raw["body"],
                            url=raw["url"], elapsed=raw["elapsed"])
            log.verb(f"response headers: {self._headers_line(resp.headers)}")
            self._log_text("response body", resp.body, limit)
            log.step_pop(f"{resp.status} {resp.reason} "
                         f"({resp.elapsed:.3f}s)")
            popped = True
        finally:
            if not popped:
                log.step_pop("failed")
        if ok and not resp.ok:
            raise HttpError(
                f"{method} {path} -> {resp.status} {resp.reason}: "
                f"{_excerpt(resp.body)}", response=resp)
        return resp

    def get(self, path, *, params=None, headers=None, ok=True,
            timeout=None, log_body=None) -> Response:
        return self.request("GET", path, params=params, headers=headers,
                            ok=ok, timeout=timeout, log_body=log_body)

    def delete(self, path, *, params=None, headers=None, ok=True,
               timeout=None, log_body=None) -> Response:
        return self.request("DELETE", path, params=params, headers=headers,
                            ok=ok, timeout=timeout, log_body=log_body)

    def post(self, path, *, params=None, json=None, form=None, data=None,
             content_type=None, headers=None, ok=True, timeout=None,
             log_body=None) -> Response:
        return self.request("POST", path, params=params, json=json,
                            form=form, data=data, content_type=content_type,
                            headers=headers, ok=ok, timeout=timeout,
                            log_body=log_body)

    def put(self, path, *, params=None, json=None, form=None, data=None,
            content_type=None, headers=None, ok=True, timeout=None,
            log_body=None) -> Response:
        return self.request("PUT", path, params=params, json=json,
                            form=form, data=data, content_type=content_type,
                            headers=headers, ok=ok, timeout=timeout,
                            log_body=log_body)

    def set_header(self, name: str, value: str | None) -> None:
        """Set (or, with None, remove) a session default header."""
        self._ship(_ops.set_header, f"set_header {name}", self._client,
                   name, value)

    def cookies(self) -> dict[str, str]:
        """Return the session cookies as a name -> value dict."""
        return self._ship(_ops.cookies, "cookies", self._client)


@contextmanager
def session(pco, base_url: str, *, timeout: float = 30.0,
            verify: bool = True, headers: dict[str, str] | None = None,
            log_body: int = DEFAULT_LOG_BODY,
            redact: Iterable[str] = ()) -> Iterator[Session]:
    """Open an HTTP session against *base_url* from pco's agent."""
    log.step_push(f"HTTP session: {base_url}")
    popped = False
    try:
        with remote.python(pco, timeout=timeout + TRANSPORT_MARGIN) as rem:
            if not verify:
                log.ring(f"TLS verification disabled for {base_url}")
            client = _ship(rem, _ops.bootstrap, f"bootstrap {base_url}",
                           base_url, verify, dict(headers or {}), MAX_BODY)
            log.step_pop("HTTP session ready")
            popped = True
            yield Session(rem, client, timeout=timeout, log_body=log_body,
                          redact=frozenset(x.lower() for x in redact))
    finally:
        if not popped:
            log.step_pop("failed")
