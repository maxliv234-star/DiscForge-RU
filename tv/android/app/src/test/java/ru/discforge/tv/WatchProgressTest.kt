package ru.discforge.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WatchProgressTest {
    @Test fun bookmarkIdentitySurvivesIpChanges() {
        val one = WatchProgress.bookmarkKeyByToken("test-key-which-is-long-enough", "abcd")
        val two = WatchProgress.bookmarkKeyByToken("test-key-which-is-long-enough", "abcd")
        val another = WatchProgress.bookmarkKeyByToken("another-test-key-which-is-long", "abcd")
        assertEquals(one, two)
        assertFalse(one == another)
        assertEquals("2:03", WatchProgress.timeLabel(7_380_000L))
    }

    @Test fun bookmarksAreIsolatedPerServerAndFile() {
        val first = WatchProgress.bookmarkKey("http://192.168.1.10:8098", "abcd1234")
        val second = WatchProgress.bookmarkKey("http://192.168.1.20:8098", "abcd1234")
        val third = WatchProgress.bookmarkKey("http://192.168.1.10:8098", "ffff1234")
        assertFalse(first == second)
        assertFalse(first == third)
        assertEquals("http://192.168.1.10:8098/api/v1/media/abcd1234", first)
    }

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
