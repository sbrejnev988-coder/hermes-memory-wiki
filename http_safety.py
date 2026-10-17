"""Small stdlib HTTP boundary helpers shared by credential-bearing clients."""
from __future__ import annotations

import urllib.request
import urllib.parse
import ipaddress
from typing import Any


_ORIGINAL_URLOPEN = urllib.request.urlopen


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an HTTPError before credentials can move."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def urlopen_no_redirect(request: Any, *, timeout: float, _before_dispatch=None):
    """Open one URL while refusing HTTP redirects.

    Tests in this repository traditionally replace ``urllib.request.urlopen``
    after import. Preserve that injected transport; the production path keeps
    the original function identity and always uses the no-redirect opener.
    """
    transport = urllib.request.urlopen
    if transport is not _ORIGINAL_URLOPEN:
        if _before_dispatch is not None:
            timeout = min(timeout, _before_dispatch())
            if timeout <= 0:
                raise TimeoutError('HTTP original deadline exceeded')
        return transport(request, timeout=timeout)
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    hostname = (urllib.parse.urlsplit(url).hostname or "").lower()
    try:
        loopback = hostname == "localhost" or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname == "localhost"
    handlers: list[Any] = [_NoRedirectHandler()]
    if loopback:
        # Local Qdrant/embedding credentials must never traverse an inherited
        # HTTP_PROXY even when the process has no NO_PROXY configuration.
        handlers.append(urllib.request.ProxyHandler({}))
    # Finish opener/route/Request/codec preparation before original admission.
    # This is a synchronous snapshot, not an atomic SQL-to-wire lease.
    opened = urllib.request.build_opener(*handlers).open
    if _before_dispatch is not None:
        timeout = min(timeout, _before_dispatch())
        if timeout <= 0:
            raise TimeoutError('HTTP original deadline exceeded')
    return opened(request, timeout=timeout)
