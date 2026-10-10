package ru.discforge.tv

import android.os.SystemClock
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Authenticate UDP advertisements with HMAC(token, fresh nonce).
 * Do not send the token to unauthenticated peers even over HTTP.
 */
object LanDiscovery {
    private const val REQUEST = "DISCFORGE_TV_DISCOVER_V2:"
    private const val RESPONSE = "DISCFORGE_TV_SERVER_V2:"
    private const val PORT = 8099

    fun proof(token: String, nonce: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(token.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        return mac.doFinal(nonce.toByteArray(Charsets.US_ASCII))
            .take(16).joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
    }

    fun parseReply(text: String, host: String, token: String, nonce: String): String? {
        if (!text.startsWith(RESPONSE)) return null
        val parts = text.removePrefix(RESPONSE).split(":")
        if (parts.size != 2) return null
        val port = parts[0].toIntOrNull() ?: return null
        val advertised = parts[1]
        if (!advertised.matches(Regex("[a-f0-9]{32}"))) return null
        val expected = proof(token, nonce)
        if (!MessageDigest.isEqual(advertised.toByteArray(Charsets.US_ASCII),
                expected.toByteArray(Charsets.US_ASCII))) return null
        return ServerAddress.normalize(host + ":" + port)
    }

    /** Best effort; some access points block LAN broadcast. */
    fun discover(token: String): List<String> {
        val found = linkedSetOf<String>()
        try {
            val nonceBytes = ByteArray(16)
            SecureRandom().nextBytes(nonceBytes)
            val nonce = nonceBytes.joinToString("") { byte ->
                "%02x".format(byte.toInt() and 0xff)
            }
            DatagramSocket().use { socket ->
                socket.broadcast = true
                socket.soTimeout = 350
                val data = (REQUEST + nonce).toByteArray(Charsets.US_ASCII)
                val query = DatagramPacket(data, data.size,
                    InetAddress.getByName("255.255.255.255"), PORT)
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
                            reply.address.hostAddress ?: "", token, nonce)
                        if (candidate != null) found.add(candidate)
                    } catch (_: java.net.SocketTimeoutException) {
                        // Continue until deadline.
                    }
                }
            }
        } catch (_: Exception) {
            // Saved server address and manual connect still work.
        }
        return found.toList()
    }
}
