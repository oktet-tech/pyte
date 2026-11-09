# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Agent-side HTTP client ops shipped to the test agent via pyte.remote.

Each function runs in the agent's python3 (started by pyte.remote). It
MUST be self-contained: all imports inside the body, no closures, no
module-level references, no calls to siblings here (helpers are nested
defs). That is why this module has no module-level imports at all.
Only the Python standard library is available on the agent. The live
Client crosses back as a RemoteObject (bootstrap) and is passed back in
as ``client``.
"""


def bootstrap(base_url, verify, headers, max_body):
    """Build the cookie-keeping stdlib HTTP client and return it."""
    import http.cookiejar
    import json as jsonlib
    import ssl
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    class Client:
        """Cookie-keeping HTTP session; request() returns a plain dict."""

        def __init__(self):
            self.base_url = base_url
            self.max_body = max_body
            self.timeout = None
            self.headers = dict(headers)
            self.jar = http.cookiejar.CookieJar()
            ctx = ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self.ssl_context = ctx
            self.opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPCookieProcessor(self.jar),
                urllib.request.HTTPSHandler(context=ctx))

        def cookies(self):
            return {c.name: c.value for c in self.jar}

        def set_header(self, name, value):
            for key in [k for k in self.headers
                        if k.lower() == name.lower()]:
                del self.headers[key]
            if value is not None:
                self.headers[name] = value

        def request(self, method, path, params=None, json=None, form=None,
                    data=None, content_type=None, headers=None,
                    timeout=None):
            kinds = [x for x in (json, form, data) if x is not None]
            if len(kinds) > 1:
                raise RuntimeError(
                    "json, form and data are mutually exclusive")
            body = None
            ctype = None
            if json is not None:
                body = jsonlib.dumps(json).encode("utf-8")
                ctype = "application/json"
            elif form is not None:
                body = urllib.parse.urlencode(form, doseq=True).encode()
                ctype = "application/x-www-form-urlencoded"
            elif data is not None:
                if content_type is None:
                    raise RuntimeError("data requires content_type")
                body = data.encode("utf-8") if isinstance(data, str) else data
                ctype = content_type
            if content_type is not None:
                ctype = content_type

            if path.startswith(("http://", "https://")):
                url = path
            else:
                url = urllib.parse.urljoin(
                    self.base_url.rstrip("/") + "/", path.lstrip("/"))
            if params:
                url += ("&" if "?" in url else "?") + \
                    urllib.parse.urlencode(params, doseq=True)

            merged = {}
            for src in (self.headers, headers or {}):
                for k, v in src.items():
                    for old in [o for o in merged if o.lower() == k.lower()]:
                        del merged[old]
                    merged[k] = v
            if ctype is not None and not any(
                    k.lower() == "content-type" for k in merged):
                merged["Content-Type"] = ctype

            req = urllib.request.Request(url, data=body, method=method,
                                         headers=merged)
            if timeout is None:
                timeout = self.timeout
            kw = {} if timeout is None else {"timeout": timeout}
            start = time.monotonic()
            try:
                resp = self.opener.open(req, **kw)
            except urllib.error.HTTPError as exc:
                resp = exc
            try:
                raw = resp.read(self.max_body + 1)
                if len(raw) > self.max_body:
                    size = resp.headers.get("Content-Length")
                    known = bool(size and size.isdigit())
                    size = int(size) if known else len(raw)
                    raise RuntimeError(
                        "response body %s%d bytes exceeds the %d byte cap"
                        % ("" if known else "at least ", size,
                           self.max_body))
                status = resp.status if hasattr(resp, "status") else resp.code
                reason = resp.reason
                final_url = resp.geturl()
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                charset = resp.headers.get_content_charset() or "utf-8"
            finally:
                resp.close()
            elapsed = time.monotonic() - start
            try:
                text = raw.decode(charset, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            try:
                parsed = jsonlib.loads(text)
            except ValueError:
                parsed = None
            return {"status": status, "reason": reason, "headers": hdrs,
                    "body": text, "url": final_url, "json": parsed,
                    "elapsed": elapsed}

    return Client()


def request(client, method, path, kw):
    """Issue one request on *client*; kw are Client.request keyword args.

    Bytes bodies cross the transport as ``data_b64`` (base64 text).
    """
    kw = dict(kw)
    if "data_b64" in kw:
        import base64
        kw["data"] = base64.b64decode(kw.pop("data_b64"))
    import json
    r = client.request(method, path, **kw)
    r.pop("json", None)
    size = len(json.dumps(r["body"]))
    if size > client.max_body:
        raise RuntimeError(
            "response body %d bytes exceeds the %d byte cap"
            % (size, client.max_body))
    return r


def set_header(client, name, value):
    """Set (or, with None, remove) a session default header."""
    client.set_header(name, value)


def cookies(client):
    """Return the session cookie jar as a name -> value dict."""
    return client.cookies()
