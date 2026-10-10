package ru.discforge.tv

import android.os.SystemClock
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/** Best-effort LAN discovery: no credentials are included in UDP packets. */
object LanDiscovery {
    private const val REQUEST = "DISCFORGE_TV_DISCOVER_V1"
    private const val RESPONSE = "DISCFORGE_TV_SERVER_V1:"
    private const val PORT = 8099

    fun parseReply(text: String, host: String): String? {
        if (!text.startsWith(RESPONSE)) return null
        val digits = text.removePrefix(RESPONSE)
        if (digits.isEmpty() || digits.any { !it.isDigit() }) return null
        val port = digits.toIntOrNull() ?: return null
        return ServerAddress.normalize(host + ":" + port)
    }

    /** Call from worker thread, never UI. Saved token is verified via HTTP afterward. */
    fun discover(): List<String> {
        val found = linkedSetOf<String>()
        try {
            DatagramSocket().use { socket ->
                socket.broadcast = true
                socket.soTimeout = 350
                val data = REQUEST.toByteArray(Charsets.US_ASCII)
                val query = DatagramPacket(data, data.size,
                    InetAddress.getByName("255.255.255.255"), PORT)
                // Multiple broadcasts help on noisy home Wi-Fi.
                socket.send(query)
                socket.send(query)
                val endAt = SystemClock.elapsedRealtime() + 1700L
                while (SystemClock.elapsedRealtime() < endAt) {
                    val bytes = ByteArray(128)
                    val reply = DatagramPacket(bytes, bytes.size)
                    try {
                        socket.receive(reply)
                        val candidate = parseReply(
                            String(reply.data, reply.offset, reply.length, Charsets.US_ASCII),
                            reply.address.hostAddress ?: "")
                        if (candidate != null) found.add(candidate)
                    } catch (_: java.net.SocketTimeoutException) {
                        // Continue until deadline.
                    }
                }
            }
        } catch (_: Exception) {
            // Some Wi-Fi firmwares filter broadcast. Manual saved address still works.
        }
        return found.toList()
    }
}
