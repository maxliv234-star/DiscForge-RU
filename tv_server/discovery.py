"""Authenticated discovery of a previously paired LAN media server.

The shared pairing token never leaves the server in UDP packets. Each reply
contains a truncated HMAC of a fresh client nonce, so only paired servers
can advertise a new IP address to the client.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import socket
from threading import Event, Thread

REQUEST_PREFIX = b"DISCFORGE_TV_DISCOVER_V2:"
RESPONSE_PREFIX = b"DISCFORGE_TV_SERVER_V2:"
NONCE_PATTERN = re.compile(rb"[a-f0-9]{32}")


def is_lan_client(address: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        return False
    return ip.is_loopback or ip in ipaddress.IPv4Network("10.0.0.0/8") or (
        ip in ipaddress.IPv4Network("172.16.0.0/12")) or (
        ip in ipaddress.IPv4Network("192.168.0.0/16"))


def authenticated_reply(request: bytes, http_port: int, token: str) -> bytes | None:
    if not request.startswith(REQUEST_PREFIX):
        return None
    nonce = request[len(REQUEST_PREFIX):]
    if NONCE_PATTERN.fullmatch(nonce) is None:
        return None
    proof = hmac.new(token.encode("utf-8"), nonce, hashlib.sha256).hexdigest()[:32]
    return RESPONSE_PREFIX + str(http_port).encode("ascii") + b":" + proof.encode("ascii")


class Discovery:
    def __init__(self, udp_port: int, http_port: int, token: str):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", udp_port))
        self.sock.settimeout(0.5)
        self.http_port = http_port
        self.token = token
        self.stopped = Event()
        self.thread = Thread(target=self.run, daemon=True, name="discforge-discovery")
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            try:
                message, sender = self.sock.recvfrom(128)
                if is_lan_client(sender[0]):
                    reply = authenticated_reply(message, self.http_port, self.token)
                    if reply is not None:
                        self.sock.sendto(reply, sender)
            except socket.timeout:
                continue
            except OSError:
                break

    def close(self):
        self.stopped.set()
        self.sock.close()
        self.thread.join(timeout=2)


def start_discovery(udp_port: int, http_port: int, token: str) -> Discovery | None:
    try:
        listener = Discovery(udp_port, http_port, token)
    except OSError as exc:
        print(f"UDP discovery unavailable: {exc}", flush=True)
        return None
    print(f"DiscForge TV LAN discovery: UDP {udp_port}", flush=True)
    return listener
