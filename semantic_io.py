"""Semantic HTTP byte boundaries; no configuration or provider selection.

The cap+1 admission follows extractor._read_response. Native completion uses
Google Drive's existing per-response chunk observer pattern, not JSON syntax.
The curl helper exists solely because subprocess.run(capture_output=True)
accumulates both pipes without a bound. It owns only the direct child/pipes;
SOURCE seams do not prove native kill, descendant containment or libcurl framing.
"""
from __future__ import annotations

import http.client
import io
import json
import math
import subprocess
import threading
import time

REQUEST_MAX_BYTES = 8_000_000
RESPONSE_MAX_BYTES = 2_000_000
CURL_STDERR_MAX_BYTES = 8192
CURL_CONFIG_OVERHEAD_BYTES = 65_536


class SemanticIOError(ValueError):
    """Fixed, content-free reason. Never retain a provider body in diagnostics."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _cap(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise SemanticIOError("invalid_io_bound")


def request_bytes(body, *, ensure_ascii=True, check=None, cap=REQUEST_MAX_BYTES):
    """Admit the whole serialized UTF-8 body, never truncate an ACL/filter.

    Incremental encoding also avoids constructing an arbitrarily large complete
    JSON string for has_id. Individual strings are charged before UTF-8 encode.
    Caller-owned inputs and the JSON encoder's single-token workspace are not
    an OS memory ceiling.
    """
    _cap(cap, REQUEST_MAX_BYTES)
    if check is not None:
        check()
    if body is None:
        return None
    data = bytearray()
    for part in json.JSONEncoder(ensure_ascii=ensure_ascii).iterencode(body):
        if check is not None:
            check()
        remaining = cap - len(data)
        if len(part) > remaining:
            raise SemanticIOError("request_too_large")
        encoded = part.encode("utf-8")
        if len(encoded) > remaining:
            raise SemanticIOError("request_too_large")
        data.extend(encoded)
    if check is not None:
        check()
    return bytes(data)


class _ChunkCompletionReader:
    """Observe bounded native framing operations on this response only."""
    def __init__(self, response, cap, check):
        self.response, self.fp, self.check = response, response.fp, check
        self.remaining = cap + 65_536
        self.terminal_line = False

    def _charge(self, data):
        if self.check is not None:
            self.check()
        if not isinstance(data, bytes) or len(data) > self.remaining:
            raise SemanticIOError("response_framing")
        self.remaining -= len(data)

    def read(self, amount):
        if self.check is not None:
            self.check()
        if amount < 0 or amount > self.remaining:
            raise SemanticIOError("response_framing")
        data = self.fp.read(amount)
        self._charge(data)
        if self.response.chunk_left == 0 and amount == 2 and data != b"\r\n":
            raise SemanticIOError("response_incomplete")
        return data

    def read1(self, amount):
        if self.check is not None:
            self.check()
        if amount < 0 or amount > self.remaining:
            raise SemanticIOError("response_framing")
        data = self.fp.read1(amount)
        self._charge(data)
        return data

    def readline(self, limit):
        if self.check is not None:
            self.check()
        if limit <= 0:
            raise SemanticIOError("response_framing")
        line = self.fp.readline(min(limit, self.remaining + 1))
        self._charge(line)
        if not line.endswith(b"\r\n"):
            raise SemanticIOError("response_incomplete")
        self.terminal_line = line == b"\r\n"
        return line

    def close(self):
        self.fp.close()


def complete_body(response, *, check=None, cap=RESPONSE_MAX_BYTES):
    """Bound retained body and every read before decode. Require known framing.

    Supports urllib's native HTTPResponse (including HTTPError.fp) and an
    explicitly in-memory BytesIO seam. A short/parsable prefix is not completion.
    Close belongs to the caller, including exceptions and malformed bodies.
    read1 avoids a single cap-sized blocking read through a slowly dripped body;
    checks fence publication, not OS-level hard interruption of a blocked read.
    """
    _cap(cap, RESPONSE_MAX_BYTES)
    if check is not None:
        check()
    headers = getattr(response, "headers", None)
    if headers is None:
        raise SemanticIOError("response_framing")
    if hasattr(headers, "get_all"):
        if (len(headers.get_all("Content-Length", [])) > 1
                or len(headers.get_all("Transfer-Encoding", [])) > 1):
            raise SemanticIOError("response_framing")
    length = headers.get("Content-Length")
    declared = None
    if length is not None:
        if (not isinstance(length, str) or len(length) > 20
                or not length.strip().isascii() or not length.strip().isdecimal()):
            raise SemanticIOError("response_framing")
        declared = int(length.strip())
        if declared > cap:
            raise SemanticIOError("response_too_large")
    stream = response if isinstance(response, http.client.HTTPResponse) else getattr(response, "fp", None)
    native = isinstance(stream, http.client.HTTPResponse)
    transfer = headers.get("Transfer-Encoding", "")
    tap = None
    if native:
        if stream.fp is None or stream.isclosed():
            raise SemanticIOError("response_framing")
        if stream.chunked:
            if declared is not None or transfer.strip().lower() != "chunked":
                raise SemanticIOError("response_framing")
            tap = _ChunkCompletionReader(stream, cap, check)
            stream.fp = tap
        elif transfer or stream.length != declared:
            raise SemanticIOError("response_framing")
    elif not isinstance(stream, io.BytesIO) or transfer or stream.tell() != 0:
        raise SemanticIOError("response_framing")
    data = bytearray()
    eof = False
    try:
        while len(data) <= cap:
            if check is not None:
                check()
            amount = min(65_536, cap + 1 - len(data))
            try:
                part = stream.read1(amount) if native else response.read(amount)
            except (http.client.HTTPException, OSError) as exc:
                # IncompleteRead may contain private partial data; do not retain it.
                if isinstance(exc, TimeoutError):
                    raise TimeoutError("semantic_io_timeout") from None
                raise SemanticIOError("response_incomplete") from None
            if check is not None:
                check()
            if not isinstance(part, bytes) or len(part) > amount:
                raise SemanticIOError("response_framing")
            if not part:
                eof = True
                break
            data.extend(part)
            if native and stream.isclosed():
                break
        if len(data) > cap:
            raise SemanticIOError("response_too_large")
        if declared is not None and len(data) != declared:
            raise SemanticIOError("response_incomplete")
        if native:
            if not stream.isclosed() or (declared is not None and stream.length != 0):
                raise SemanticIOError("response_incomplete")
            if tap is not None and (stream.chunk_left is not None or not tap.terminal_line):
                raise SemanticIOError("response_incomplete")
        elif not eof:
            raise SemanticIOError("response_incomplete")
        if check is not None:
            check()
        return bytes(data)
    finally:
        if tap is not None and stream.fp is tap:
            stream.fp = tap.fp


def json_body(raw, *, check=None, allow_empty=False, cap=RESPONSE_MAX_BYTES):
    """This size assertion is secondary; transport already bounded accumulation."""
    _cap(cap, RESPONSE_MAX_BYTES)
    if not isinstance(raw, bytes):
        raise SemanticIOError("response_framing")
    if check is not None:
        check()
    if len(raw) > cap:
        raise SemanticIOError("response_too_large")
    if not raw and allow_empty:
        return {}
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise SemanticIOError("response_utf8") from None
    try:
        result = json.loads(text)
    except (ValueError, RecursionError):
        raise SemanticIOError("response_json") from None
    if not isinstance(result, dict):
        raise SemanticIOError("response_schema")
    if check is not None:
        check()
    return result


def response_json(response, *, check=None, allow_empty=False, cap=RESPONSE_MAX_BYTES):
    return json_body(complete_body(response, check=check, cap=cap),
                     check=check, allow_empty=allow_empty, cap=cap)


_CURL_LOCK = threading.Lock()
_CURL_RETAINED = []


def curl_capture(cmd, config_input, timeout, *, check=None, cleanup_remaining=None,
                 stdout_cap=RESPONSE_MAX_BYTES, stderr_cap=CURL_STDERR_MAX_BYTES,
                 _popen=None):
    """Minimal curl-only binary pipe capture; never communicate/capture_output.

    Three direct pipe workers, cap+1 refusal, shared request deadline and bounded
    cleanup. Unknown child/worker/pipe closure retains its exact owner and denies
    another curl launch. No process tree/OS sandbox/host ACK contract is claimed.
    _popen is an internal SOURCE synthetic-process seam, not another provider.
    """
    _cap(stdout_cap, RESPONSE_MAX_BYTES)
    _cap(stderr_cap, CURL_STDERR_MAX_BYTES)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise SemanticIOError("invalid_io_bound")
    if type(config_input) is not bytes or len(config_input) > REQUEST_MAX_BYTES * 2 + CURL_CONFIG_OVERHEAD_BYTES:
        raise SemanticIOError("request_too_large")
    with _CURL_LOCK:
        if _CURL_RETAINED:
            raise SemanticIOError("curl_cleanup_unknown")
    if check is not None:
        check()
    deadline = time.monotonic() + timeout
    proc, threads = None, {}
    raw = {"stdout": bytearray(), "stderr": bytearray()}
    completed, problems = {}, []
    exceeded = threading.Event()
    primary = None

    def reader(name, pipe, cap):
        try:
            while len(raw[name]) <= cap:
                amount = min(4096, cap + 1 - len(raw[name]))
                chunk = pipe.read(amount)
                if not isinstance(chunk, bytes) or len(chunk) > amount:
                    raise SemanticIOError("curl_pipe_error")
                if not chunk:
                    completed[name] = True
                    return
                raw[name].extend(chunk)
                if len(raw[name]) > cap:
                    exceeded.set()
                    return
        except BaseException:
            problems.append("curl_pipe_error")
        finally:
            try:
                pipe.close()
            except BaseException:
                problems.append("curl_cleanup_unknown")

    def writer():
        try:
            offset = 0
            while offset < len(config_input):
                part = config_input[offset:offset + 4096]
                count = proc.stdin.write(part)
                if type(count) is not int or not 0 < count <= len(part):
                    raise SemanticIOError("curl_pipe_error")
                offset += count
            proc.stdin.close()
            completed["stdin"] = True
        except BaseException:
            problems.append("curl_pipe_error")
        finally:
            try:
                proc.stdin.close()
            except BaseException:
                problems.append("curl_cleanup_unknown")

    try:
        factory = subprocess.Popen if _popen is None else _popen
        proc = factory(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, shell=False, close_fds=True, bufsize=0)
        for name, target, args in (("stdout", reader, ("stdout", proc.stdout, stdout_cap)),
                                   ("stderr", reader, ("stderr", proc.stderr, stderr_cap)),
                                   ("stdin", writer, ())):
            thread = threading.Thread(target=target, args=args, name="wiki-curl-" + name, daemon=True)
            threads[name] = thread
            thread.start()
        while True:
            rc = proc.poll()
            if check is not None:
                check()
            if time.monotonic() >= deadline:
                raise TimeoutError("semantic_io_timeout")
            if exceeded.is_set():
                raise SemanticIOError("response_too_large")
            if problems:
                raise SemanticIOError(problems[0])
            if (rc is not None and len(completed) == 3
                    and all(not thread.is_alive() for thread in threads.values())):
                if rc != 0:
                    raise SemanticIOError("curl_exit_nonzero")
                break
            time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
    except BaseException as exc:
        primary = exc
    finally:
        # Existing prefetch owner supplies remaining cleanup time, not a new
        # five-second allowance. Ordinary direct calls have a three-second cap.
        try:
            remaining = 3.0 if cleanup_remaining is None else max(0.0, min(3.0, cleanup_remaining()))
        except BaseException:
            remaining = 0.0
        cleanup_deadline = time.monotonic() + remaining
        reaped = proc is None
        cleanup_errors = []
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.kill()
            except BaseException:
                cleanup_errors.append("kill")
            try:
                terminal = proc.wait(timeout=max(0.0, cleanup_deadline - time.monotonic()))
                if type(terminal) is not int:
                    raise SemanticIOError("curl_cleanup_unknown")
                reaped = True
            except BaseException:
                cleanup_errors.append("wait")
        for thread in threads.values():
            if thread.ident is not None:
                try:
                    thread.join(max(0.0, cleanup_deadline - time.monotonic()))
                except BaseException:
                    cleanup_errors.append("join")
        live = {name for name, thread in threads.items() if thread.is_alive()}
        if proc is not None:
            for name in ("stdin", "stdout", "stderr"):
                if name not in live:
                    try:
                        getattr(proc, name).close()
                    except BaseException:
                        cleanup_errors.append("close")
        closed = proc is None or all(getattr(proc, name).closed for name in ("stdin", "stdout", "stderr"))
        if not reaped or live or not closed or cleanup_errors:
            with _CURL_LOCK:
                _CURL_RETAINED.append((proc, threads, raw))
            if primary is None:
                primary = SemanticIOError("curl_cleanup_unknown")
            # Preserve primary cancellation/deadline; publish only a fixed note.
            primary.add_note("curl_cleanup_unknown")
    if primary is not None:
        raise primary
    if check is not None:
        check()
    if time.monotonic() >= deadline:
        raise TimeoutError("semantic_io_timeout")
    return bytes(raw["stdout"])
