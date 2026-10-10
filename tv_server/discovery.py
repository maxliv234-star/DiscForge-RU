"""Optional local UDP discovery. Never sends the authentication token over UDP."""
from __future__ import annotations

import ipaddress
import socket
from threading import Event, Thread

REQUEST = b"DISCFORGE_TV_DISCOVER_V1"
RESPONSE_PREFIX = b"DISCFORGE_TV_SERVER_V1:"


def is_lan_client(address: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        return False
    return ip.is_loopback or ip in ipaddress.IPv4Network("10.0.0.0/8") or (
        ip in ipaddress.IPv4Network("172.16.0.0/12")) or (
        ip in ipaddress.IPv4Network("192.168.0.0/16"))


class Discovery:
    def __init__(self, udp_port: int, http_port: int):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", udp_port))
        self.sock.settimeout(0.5)
        self.http_port = http_port
        self.stopped = Event()
        self.thread = Thread(target=self.run, daemon=True, name="discforge-discovery")
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                message, sender = self.sock.recvfrom(128)
                if message == REQUEST and is_lan_client(sender[0]):
                    self.sock.sendto(RESPONSE_PREFIX + str(self.http_port).encode("ascii"), sender)
            except socket.timeout:
                continue
            except OSError:
                break

    def close(self):
        self.stopped.set()
        self.sock.close()
        self.thread.join(timeout=2)


def start_discovery(udp_port: int, http_port: int) -> Discovery | None:
    try:
        listener = Discovery(udp_port, http_port)
    except OSError as exc:
        print(f"UDP discovery unavailable: {exc}", flush=True)
        return None
    print(f"DiscForge TV LAN discovery: UDP {udp_port}", flush=True)
    return listener
