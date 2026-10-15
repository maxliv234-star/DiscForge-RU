package ru.discforge.tv

import java.net.URI

/** Avoid sending secrets to non-local websites; use private IPv4 hosts only. */
object ServerAddress {
    fun normalize(input: String): String? {
        val value = input.trim()
        if (value.isEmpty()) return null
        val candidate = if ("://" in value) value else "http://$value"
        val parsed = try { URI(candidate) } catch (_: Exception) { return null }
        if (parsed.scheme != "http" || parsed.userInfo != null ||
            parsed.rawQuery != null || parsed.rawFragment != null ||
            parsed.path !in listOf("", null, "/")) return null
        val host = parsed.host ?: return null
        if (!isLocalIPv4(host)) return null
        val port = if (parsed.port == -1) 8098 else parsed.port
        if (port !in 1..65535) return null
        return "http://$host:$port"
    }

    private fun isLocalIPv4(host: String): Boolean {
        val parts = host.split(".")
        if (parts.size != 4 || parts.any { it.isEmpty() || it.length > 3 ||
                    it.any { char -> char !in '0'..'9' } }) return false
        val octets = parts.map { it.toIntOrNull() ?: return false }
        if (octets.any { it !in 0..255 }) return false
        val (a, b) = octets
        return a == 10 || (a == 172 && b in 16..31) ||
                (a == 192 && b == 168) || (a == 127 && b == 0)
    }
}
