import operator
import re
import socket
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Final
from urllib.parse import parse_qs, urlsplit

HOST: Final = "localhost"
PORT: Final = 8080
MAX_HEADER_BYTES: Final = 16 * 1024
MAX_BODY_BYTES: Final = 1024 * 1024
HEADER_END: Final = b"\r\n\r\n"
HEADER_NAME: Final = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
NUMBER: Final = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
STATUS: Final = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}
OPERATIONS: Final = {"/add": operator.add, "/sub": operator.sub, "/mul": operator.mul, "/div": operator.truediv}


@dataclass(frozen=True, slots=True)
class Request:
    method: str
    target: str
    headers: dict[str, str]
    valid_line: bool


class FramingError(Exception):
    pass

def parse_head(raw: bytes) -> tuple[Request, int]:
    lines = raw.decode("iso-8859-1").split("\r\n")
    words = lines[0].split(" ")
    valid_line = (
        len(words) == 3
        and all(words)
        and HEADER_NAME.fullmatch(words[0]) is not None
        and words[2] == "HTTP/1.1"
        and words[1].startswith("/")
        and all(0x21 <= ord(character) <= 0x7E for character in words[1])
    )
    method, target = (words[0], words[1]) if valid_line else ("", "")

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            raise FramingError
        name, value = line.split(":", 1)
        if HEADER_NAME.fullmatch(name) is None:
            raise FramingError
        name = name.lower()
        if name in headers and name in {"content-length", "host", "transfer-encoding"}:
            raise FramingError
        headers[name] = value.strip()

    if "transfer-encoding" in headers:
        raise FramingError
    length_text = headers.get("content-length", "0")
    if not length_text.isascii() or not length_text.isdigit():
        raise FramingError
    digits = length_text.lstrip("0") or "0"
    if len(digits) > len(str(MAX_BODY_BYTES)):
        raise FramingError
    length = int(digits)
    if length > MAX_BODY_BYTES:
        raise FramingError
    return Request(method, target, headers, valid_line), length


def read_complete_request(connection: socket.socket, receive_buffer: bytes) -> tuple[Request | None, bytes]:
    while True:
        header_boundary = receive_buffer.find(HEADER_END)
        if header_boundary >= 0:
            if header_boundary > MAX_HEADER_BYTES:
                raise FramingError
            break
        if len(receive_buffer) > MAX_HEADER_BYTES + len(HEADER_END):
            raise FramingError
        chunk = connection.recv(4096)
        if not chunk:
            if receive_buffer:
                raise FramingError
            return None, b""
        receive_buffer += chunk

    request, body_length = parse_head(receive_buffer[:header_boundary])
    request_boundary = header_boundary + len(HEADER_END) + body_length
    while len(receive_buffer) < request_boundary:
        chunk = connection.recv(4096)
        if not chunk:
            raise FramingError
        receive_buffer += chunk
    remaining_buffer = receive_buffer[request_boundary:]
    return request, remaining_buffer


def calculate(request: Request) -> tuple[int, bytes]:
    if not request.valid_line or not request.headers.get("host"):
        return 400, b""
    if "#" in request.target:
        return 400, b""
    try:
        target = urlsplit(request.target)
    except ValueError:
        return 400, b""
    if target.path not in {"/add", "/sub", "/mul", "/div"}:
        return 404, b""
    if request.method != "GET":
        return 405, b""

    try:
        parameters = parse_qs(target.query, keep_blank_values=True, strict_parsing=True, max_num_fields=16)
        if len(parameters.get("a", [])) != 1 or len(parameters.get("b", [])) != 1:
            return 400, b""
        a_text, b_text = parameters["a"][0], parameters["b"][0]
        if NUMBER.fullmatch(a_text) is None or NUMBER.fullmatch(b_text) is None:
            return 400, b""
        a, b = Decimal(a_text), Decimal(b_text)
        if target.path == "/div" and b == 0:
            return 400, b""
        result = OPERATIONS[target.path](a, b)
        if not result.is_finite():
            return 400, b""
        return 200, format(result.normalize(), "f").encode("ascii")
    except (ValueError, DecimalException):
        return 400, b""


def response(status: int, body: bytes) -> bytes:
    lines = [f"HTTP/1.1 {status} {STATUS[status]}", f"Content-Length: {len(body)}", "Content-Type: text/plain"]
    if status == 405:
        lines.append("Allow: GET")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


def handle_client(connection: socket.socket) -> None:
    receive_buffer = b""
    while True:
        try:
            request, receive_buffer = read_complete_request(connection, receive_buffer)
        except FramingError:
            connection.sendall(response(400, b""))
            return
        if request is None:
            return
        status, body = calculate(request)
        connection.sendall(response(status, body))


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()
        print(f"Listening on http://{HOST}:{PORT}", flush=True)
        while True:
            connection, _ = server.accept()
            with connection:
                try:
                    handle_client(connection)
                except (BrokenPipeError, ConnectionResetError):
                    continue


if __name__ == "__main__":
    main()
