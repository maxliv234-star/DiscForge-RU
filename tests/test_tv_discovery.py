"""Authenticated UDP discovery tests; discovery never discloses the token."""
import hashlib
import hmac
import socket
import unittest

from tv_server.discovery import (
    Discovery, REQUEST_PREFIX, RESPONSE_PREFIX, authenticated_reply, is_lan_client,
)

KEY = "test-key-which-is-long-enough"
NONCE = b"1234567890abcdef1234567890abcdef"


class DiscoveryTests(unittest.TestCase):
    def test_lan_filter(self):
        for address in ("192.168.50.85", "172.16.0.1", "10.0.0.1", "127.0.0.1"):
            self.assertTrue(is_lan_client(address))
        for address in ("8.8.8.8", "169.254.1.2", "::1", "nope"):
            self.assertFalse(is_lan_client(address))

    def test_nonce_hmac(self):
        request = REQUEST_PREFIX + NONCE
        reply = authenticated_reply(request, 8098, KEY)
        proof = hmac.new(KEY.encode(), NONCE, hashlib.sha256).hexdigest()[:32]
        self.assertEqual(reply, RESPONSE_PREFIX + b"8098:" + proof.encode())
        self.assertNotIn(KEY.encode(), reply)
        self.assertIsNone(authenticated_reply(REQUEST_PREFIX + b"bad", 8098, KEY))
        self.assertIsNone(authenticated_reply(b"DISCFORGE_TV_DISCOVER_V1", 8098, KEY))

    def test_udp_reply(self):
        listener = Discovery(0, 8098, KEY)
        try:
            port = listener.sock.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(1.5)
                client.sendto(REQUEST_PREFIX + NONCE, ("127.0.0.1", port))
                reply, _ = client.recvfrom(128)
                self.assertEqual(reply, authenticated_reply(REQUEST_PREFIX + NONCE, 8098, KEY))
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()
