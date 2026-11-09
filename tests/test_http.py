# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Tests for pyte.tools.http (HTTP client session)."""
from pyte.errors import HttpError, TeError, ToolError


def test_httperror_is_toolerror_with_response():
    e = HttpError("GET /x -> 404 Not Found: nope", response="resp")
    assert isinstance(e, ToolError) and isinstance(e, TeError)
    assert e.rc == 0
    assert e.response == "resp"
    assert HttpError("plain").response is None
