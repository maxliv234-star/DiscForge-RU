package ru.discforge.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LanDiscoveryTest {
    @Test fun acceptsPrivateLanCandidatesOnly() {
        assertEquals("http://192.168.50.204:8098",
            LanDiscovery.parseReply("DISCFORGE_TV_SERVER_V1:8098", "192.168.50.204"))
        assertNull(LanDiscovery.parseReply("DISCFORGE_TV_SERVER_V1:8098", "8.8.8.8"))
        assertNull(LanDiscovery.parseReply("DISCFORGE_TV_SERVER_V1:0", "192.168.50.204"))
        assertNull(LanDiscovery.parseReply("DISCFORGE_TV_SERVER_V1:bad", "192.168.50.204"))
        assertNull(LanDiscovery.parseReply("invalid", "192.168.50.204"))
    }
}
