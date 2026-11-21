"""Start Rubine: ``python -m rubine`` (from the backend/ directory)."""
from __future__ import annotations

import socket

import uvicorn

from .config import get_settings


def lan_addresses() -> list[str]:
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; selects the LAN interface
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def main() -> None:
    st = get_settings()
    scheme = "https" if st.ssl_certfile else "http"
    print("\n  Rubine AI startet …")
    print(f"  Lokal:      {scheme}://localhost:{st.port}")
    for ip in lan_addresses():
        print(f"  iPhone/WLAN: {scheme}://{ip}:{st.port}")
    print()
    uvicorn.run("rubine.main:app", host=st.host, port=st.port, ssl_certfile=st.ssl_certfile,
                ssl_keyfile=st.ssl_keyfile, proxy_headers=False, log_level="info")


if __name__ == "__main__":
    main()
