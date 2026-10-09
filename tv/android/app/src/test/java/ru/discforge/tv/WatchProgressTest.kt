package ru.discforge.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WatchProgressTest {
    @Test fun remembersAnUnfinishedFilm() {
        assertEquals(120_000L, WatchProgress.bookmark(120_000L, 3_600_000L))
        assertTrue(WatchProgress.canResume(120_000L))
    }

    @Test fun doesNotBookmarkAnUnstartedFilm() {
        assertNull(WatchProgress.bookmark(29_999L, 3_600_000L))
        assertFalse(WatchProgress.canResume(29_999L))
        assertFalse(WatchProgress.canResume(0))
    }

    @Test fun clearsBookmarkWhenFilmIsFinished() {
        assertNull(WatchProgress.bookmark(3_540_000L, 3_600_000L))
        assertNull(WatchProgress.bookmark(3_599_000L, 3_600_000L))
        assertNull(WatchProgress.bookmark(3_700_000L, 3_600_000L))
    }

    @Test fun ignoresUnknownDurationAndNegativePosition() {
        assertNull(WatchProgress.bookmark(90_000L, -1))
        assertNull(WatchProgress.bookmark(-5L, 3_600_000L))
    }
}
