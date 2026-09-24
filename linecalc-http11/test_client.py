import socket

ADDRESS = ("localhost", 8080)


def request(method: str, target: str, *, host: bool = True, body: bytes = b"") -> bytes:
    headers = f"{method} {target} HTTP/1.1\r\n"
    if host:
        headers += "Host: localhost\r\n"
    if body:
        headers += f"Content-Length: {len(body)}\r\n"
    return (headers + "\r\n").encode("ascii") + body


def read_response(connection: socket.socket, buffer: bytes) -> tuple[int, bytes, bytes, dict[str, str]]:
    while b"\r\n\r\n" not in buffer:
        chunk = connection.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before response headers")
        buffer += chunk

    header_bytes, buffer = buffer.split(b"\r\n\r\n", 1)
    lines = header_bytes.decode("ascii").split("\r\n")
    status = int(lines[0].split(" ", 2)[1])
    headers = {}
    for line in lines[1:]:
        name, value = line.split(":", 1)
        headers[name.lower()] = value.strip()
    assert "content-length" in headers, "response lacks Content-Length"
    body_length = int(headers["content-length"])
    while len(buffer) < body_length:
        chunk = connection.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before response body")
        buffer += chunk
    return status, buffer[:body_length], buffer[body_length:], headers


def main() -> None:
    cases = [
        ("GET", "/add?a=2&b=3", 200, b"5"),
        ("GET", "/sub?a=10&b=4", 200, b"6"),
        ("GET", "/mul?a=6&b=7", 200, b"42"),
        ("GET", "/div?a=9&b=3", 200, b"3"),
        ("GET", "/div?a=1&b=0", 400, b""),
        ("GET", "/add?a=x&b=3", 400, b""),
        ("GET", "/pow?a=2&b=8", 404, b""),
        ("POST", "/add", 405, b""),
    ]

    with socket.create_connection(ADDRESS, timeout=5) as connection:
        connection.settimeout(5)
        buffer = b""

        for method, target, expected_status, expected_body in cases:
            connection.sendall(request(method, target))
            status, body, buffer, headers = read_response(connection, buffer)
            assert (status, body) == (expected_status, expected_body), (method, target, status, body)
            assert int(headers["content-length"]) == len(body)
            if status == 405:
                assert headers.get("allow") == "GET"
            print(f"PASS {method} {target}: {status} {body.decode('ascii')!r}")

        connection.sendall(request("GET", "/add?a=2&b=3", host=False))
        status, body, buffer, _ = read_response(connection, buffer)
        assert (status, body) == (400, b"")
        print("PASS missing Host: 400")

        body_request = request("POST", "/add", body=b"abcde")
        connection.sendall(body_request + request("GET", "/add?a=4&b=5"))
        status, body, buffer, _ = read_response(connection, buffer)
        assert (status, body) == (405, b"")
        status, body, buffer, _ = read_response(connection, buffer)
        assert (status, body) == (200, b"9")
        print("PASS Content-Length body consumed before next request")

        fragmented = request("GET", "/sub?a=20&b=8")
        for part in (fragmented[:2], fragmented[2:12], fragmented[12:25], fragmented[25:]):
            connection.sendall(part)
        status, body, buffer, _ = read_response(connection, buffer)
        assert (status, body) == (200, b"12")
        print("PASS fragmented request")

        connection.sendall(request("GET", "/mul?a=3&b=4") + request("GET", "/div?a=8&b=2"))
        status, body, buffer, _ = read_response(connection, buffer)
        assert (status, body) == (200, b"12")
        status, body, buffer, _ = read_response(connection, buffer)
        assert (status, body) == (200, b"4")
        print("PASS two requests in one sendall, ordered responses")

        connection.sendall(request("GET", "/add?a=7&b=8"))
        status, body, buffer, _ = read_response(connection, buffer)
        assert (status, body) == (200, b"15")
        print("PASS same socket remains usable")

    print("All persistent-connection checks passed on one socket.")


if __name__ == "__main__":
    main()
