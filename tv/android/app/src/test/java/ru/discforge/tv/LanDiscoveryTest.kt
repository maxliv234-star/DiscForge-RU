package ru.discforge.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LanDiscoveryTest {
    @Test fun authenticatesPairedServerOnly() {
        val key = "test-key-which-is-long-enough"
        val nonce = "1234567890abcdef1234567890abcdef"
        val proof = LanDiscovery.proof(key, nonce)
        val payload = "DISCFORGE_TV_SERVER_V2:8098:" + proof
        assertEquals("http://192.168.50.204:8098",
            LanDiscovery.parseReply(payload, "192.168.50.204", key, nonce))
        assertNull(LanDiscovery.parseReply(payload, "8.8.8.8", key, nonce))
        assertNull(LanDiscovery.parseReply(payload, "192.168.50.204", "wrong-secret", nonce))
        assertNull(LanDiscovery.parseReply(payload, "192.168.50.204", key,
            "abcdef1234567890abcdef1234567890"))
        assertNull(LanDiscovery.parseReply("DISCFORGE_TV_SERVER_V2:8098:bad",
            "192.168.50.204", key, nonce))
    }
}
