"""UDP discovery tests; no authentication tokens are transmitted over UDP."""
import socket
import unittest

from tv_server.discovery import Discovery, REQUEST, RESPONSE_PREFIX, is_lan_client


class DiscoveryTests(unittest.TestCase):
    def test_lan_filter(self):
        for address in ("192.168.50.85", "172.16.0.1", "10.0.0.1", "127.0.0.1"):
            self.assertTrue(is_lan_client(address))
        for address in ("8.8.8.8", "169.254.1.2", "::1", "nope"):
            self.assertFalse(is_lan_client(address))

    def test_only_exact_request_gets_response(self):
        listener = Discovery(0, 8098)
        try:
            port = listener.sock.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(1.5)
                client.sendto(REQUEST, ("127.0.0.1", port))
                reply, _ = client.recvfrom(128)
                self.assertEqual(reply, RESPONSE_PREFIX + b"8098")
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()
