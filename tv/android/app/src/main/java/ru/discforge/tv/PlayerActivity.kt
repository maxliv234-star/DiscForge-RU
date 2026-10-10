package ru.discforge.tv

import android.app.Activity
import android.os.Bundle
import android.view.ViewGroup
import android.widget.FrameLayout
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView

class PlayerActivity : Activity() {
    private var engine: ExoPlayer? = null
    private var mediaKey: String? = null
    private val watchPrefs by lazy { getSharedPreferences("watch_progress", MODE_PRIVATE) }
    private lateinit var screen: PlayerView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = FrameLayout(this)
        screen = PlayerView(this).apply {
            useController = true
            controllerAutoShow = true
            isFocusable = true
        }
        layout.addView(screen, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(layout)
    }

    override fun onStart() {
        super.onStart()
        val url = intent.getStringExtra("url") ?: return finish()
        val token = intent.getStringExtra("token") ?: return finish()
        val normalizedHost = try {
            val parsed = java.net.URI(url)
            ServerAddress.normalize("http://" + parsed.host + ":" + parsed.port)
        } catch (_: Exception) { null }
        val id = url.substringAfterLast("/")
        if (normalizedHost == null ||
            !url.matches(Regex(Regex.escape(normalizedHost) + "/api/v1/media/[a-f0-9]{24}"))) {
            finish()
            return
        }
        // A relative-path hash may be the same on two different PC servers.
        mediaKey = WatchProgress.bookmarkKey(normalizedHost, id)
        val http = DefaultHttpDataSource.Factory().setDefaultRequestProperties(
            mapOf("X-DiscForge-Token" to token))
        val sourceFactory = DefaultMediaSourceFactory(DefaultDataSource.Factory(this, http))
        val player = ExoPlayer.Builder(this).setMediaSourceFactory(sourceFactory).build()
        engine = player
        screen.player = player
        player.addListener(object : Player.Listener {
            override fun onPlayerError(error: PlaybackException) {
                android.widget.Toast.makeText(this@PlayerActivity,
                    "Ошибка воспроизведения: " + error.errorCodeName,
                    android.widget.Toast.LENGTH_LONG).show()
            }
        })
        player.setMediaItem(MediaItem.fromUri(url))
        val resumeAt = watchPrefs.getLong(mediaKey!!, 0)
        if (WatchProgress.canResume(resumeAt)) {
            player.seekTo(resumeAt)
            android.widget.Toast.makeText(this, "Продолжить с сохранённого места",
                android.widget.Toast.LENGTH_SHORT).show()
        }
        player.prepare()
        player.playWhenReady = true
        screen.requestFocus()
    }

    override fun onStop() {
        val active = engine
        val key = mediaKey
        if (active != null && key != null && active.duration > 0) {
            val bookmark = WatchProgress.bookmark(active.currentPosition, active.duration)
            watchPrefs.edit().apply {
                if (bookmark == null) remove(key) else putLong(key, bookmark)
            }.apply()
        }
        mediaKey = null
        screen.player = null
        engine?.release()
        engine = null
        super.onStop()
    }
}
