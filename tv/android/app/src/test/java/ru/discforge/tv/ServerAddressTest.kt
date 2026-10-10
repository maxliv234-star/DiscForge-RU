package ru.discforge.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ServerAddressTest {
    @Test fun acceptsHomeLanIps() {
        assertEquals("http://192.168.1.5:8098", ServerAddress.normalize("192.168.1.5"))
        assertEquals("http://10.2.0.15:9000", ServerAddress.normalize("http://10.2.0.15:9000"))
        assertEquals("http://172.16.1.2:8098", ServerAddress.normalize("172.16.1.2"))
    }

    @Test fun blocksPublicDestinationsAndInjection() {
        for (value in listOf("https://8.8.8.8", "http://1.2.3.4:8098",
            "http://192.168.1.2.evil.com", "http://user@192.168.1.2",
            "http://192.168.1.2/path", "http://192.168.1.2:99999",
            "http://192.168.1.2?token=leak")) {
            assertNull(value, ServerAddress.normalize(value))
        }
    }
}
