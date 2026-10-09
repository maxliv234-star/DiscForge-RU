package ru.discforge.tv

/** Playback resume policy shared by the Activity and Android unit tests. */
object WatchProgress {
    private const val MIN_WATCHED_MS = 30_000L
    private const val FINISH_MARGIN_MS = 60_000L

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
}
