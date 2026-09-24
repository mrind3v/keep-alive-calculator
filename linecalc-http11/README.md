# Keep Alive Calculator

A small Python 3 calculator server that implements an HTTP/1.1 subset directly on a TCP socket. The main lesson is connection persistence: several requests can use one TCP connection, and the server sends one response for each request without reconnecting.

## Run

In one terminal, from the repository root:

```sh
python3 linecalc-http11/server.py
```

The server listens on `localhost:8080`. In another terminal, run the single-socket test client:

```sh
python3 linecalc-http11/test_client.py
```

The client opens exactly one TCP socket for its checks. It verifies the routes and errors, a request split across several writes, two requests sent together, a POST body followed by another request, and continued use of the socket after error responses.

You can also try an endpoint directly:

```sh
curl -i 'http://localhost:8080/add?a=2&b=3'
```

Stop the server with Ctrl-C.

## Endpoints

Each endpoint accepts `GET` with numeric query parameters `a` and `b` and returns a plain-text result with no HTML.

| Request | Result body |
| --- | --- |
| `/add?a=2&b=3` | `5` |
| `/sub?a=10&b=4` | `6` |
| `/mul?a=6&b=7` | `42` |
| `/div?a=9&b=3` | `3` |

The server sends an empty body and `Content-Length: 0` for these errors:

| Status | Cause |
| --- | --- |
| `400 Bad Request` | Missing or malformed parameters, division by zero, missing `Host`, or malformed request framing |
| `404 Not Found` | Path other than `/add`, `/sub`, `/mul`, or `/div` |
| `405 Method Not Allowed` | Method other than `GET` on a calculator path; response includes `Allow: GET` |

## Why the byte buffer matters

TCP delivers a stream of bytes, not one message per `recv()` call. A read can stop halfway through a request or include bytes from multiple requests. A persistent HTTP/1.1 connection therefore needs its own buffer.

For each request, the server finds `\r\n\r\n` to locate the end of its headers. It parses `Content-Length` (zero when absent in this assignment subset), waits for that many body bytes, and removes **only** the header and body bytes belonging to this request. Any bytes after that boundary remain in the buffer for the next request. The body is consumed even when the request will receive 405. Each response has its own accurate `Content-Length`, so the client can find the next response on the same socket.

HTTP/1.1 connections stay open by default. This server closes a connection when its peer closes it or when invalid framing makes the next request boundary unknowable. It supports origin-form targets and `Content-Length` bodies. It does not implement chunked request bodies or general-purpose HTTP server features. Clients are handled one at a time.
