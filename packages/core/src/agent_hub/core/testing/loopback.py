"""A loopback port that refuses every connection, for tests that point a child at "nothing".

A port that was bound and then released is free again: the OS can hand it to the next socket
that binds port 0, such as a test's event server on another pytest-xdist worker, which then
receives the posts meant for nobody. The port here stays reserved by a socket that is bound and
never listens, held until the process exits: a connect is refused, and no other socket can bind it.
"""

import socket

_holder: list[socket.socket] = []


def closed_port() -> int:
    """This process's reserved loopback port: bound, never listening, never released."""
    if not _holder:
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", 0))
        _holder.append(holder)
    port: int = _holder[0].getsockname()[1]
    return port


def closed_url() -> str:
    """``http://127.0.0.1:<closed_port()>``: an event server URL nothing can answer on."""
    return f"http://127.0.0.1:{closed_port()}"
