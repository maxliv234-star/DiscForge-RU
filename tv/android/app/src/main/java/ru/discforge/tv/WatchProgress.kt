package ru.discforge.tv

/** Playback resume policy shared by the Activity and Android unit tests. */
object WatchProgress {
    private const val MIN_WATCHED_MS = 30_000L
    private const val FINISH_MARGIN_MS = 60_000L

    /** Isolate bookmarks between different LAN servers with identically named files. */
    fun bookmarkKey(serverBase: String, mediaId: String): String = "$serverBase/api/v1/media/$mediaId"

    fun canResume(savedPositionMs: Long): Boolean = savedPositionMs >= MIN_WATCHED_MS

    /**
     * Return a bookmark only for a started and unfinished film.
     *
     * Unknown duration must be handled by the caller: don't erase a previous
     * bookmark just because the player hasn't loaded metadata yet.
     */
    fun bookmark(positionMs: Long, durationMs: Long): Long? {
        if (durationMs <= 0 || positionMs < MIN_WATCHED_MS) return null
        if (positionMs >= durationMs || durationMs - positionMs <= FINISH_MARGIN_MS) return null
        return positionMs
    }

    /** Stable through DHCP address changes; secret itself is never stored in a key name. */
    fun bookmarkKeyByToken(token: String, mediaId: String): String {
        val digest = java.security.MessageDigest.getInstance("SHA-256")
            .digest(token.toByteArray(Charsets.UTF_8))
        val serverId = digest.take(12).joinToString("") { byte ->
            "%02x".format(byte.toInt() and 0xff)
        }
        return "v2:" + serverId + ":" + mediaId
    }

    fun timeLabel(positionMs: Long): String {
        val minutes = (positionMs.coerceAtLeast(0L) / 60_000L)
        return (minutes / 60L).toString() + ":" +
            (minutes % 60L).toString().padStart(2, '0')
    }

}
