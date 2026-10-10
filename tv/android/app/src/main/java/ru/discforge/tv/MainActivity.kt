package ru.discforge.tv

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/** D-pad-first LAN video library, with automatic re-connect for previously paired TVs. */
class MainActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val prefs by lazy { getSharedPreferences("connection", MODE_PRIVATE) }
    private val playback by lazy { getSharedPreferences("watch_progress", MODE_PRIVATE) }
    private lateinit var serverInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var status: TextView
    private lateinit var catalog: LinearLayout
    private lateinit var settingsPanel: LinearLayout
    private var busy = false

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
    private fun label(text: String, size: Float, color: Int = Color.WHITE): TextView =
        TextView(this).apply {
            this.text = text
            textSize = size
            setTextColor(color)
            gravity = Gravity.CENTER_VERTICAL
        }

    private fun background(): GradientDrawable = GradientDrawable().apply {
        setColor(Color.rgb(26, 40, 59))
        cornerRadius = dp(12).toFloat()
        setStroke(dp(1), Color.rgb(46, 65, 87))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(11, 20, 33))
            setPadding(dp(26), dp(14), dp(26), dp(14))
        }
        setContentView(root)

        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val title = label("DISCFORGE  /  TV", 27f).apply {
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.rgb(242, 247, 255))
        }
        header.addView(title, LinearLayout.LayoutParams(0, dp(55), 1f))
        val refresh = Button(this).apply {
            text = "↻  Обновить"
            setOnClickListener { loadCatalog() }
        }
        header.addView(refresh)
        val settings = Button(this).apply {
            text = "⚙  Сервер"
            setOnClickListener {
                settingsPanel.visibility =
                    if (settingsPanel.visibility == View.VISIBLE) View.GONE else View.VISIBLE
            }
        }
        header.addView(settings)
        root.addView(header)

        status = label("Домашняя медиатека · Full HD", 15f, Color.rgb(165, 191, 213))
        root.addView(status)

        settingsPanel = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = background()
            setPadding(dp(10), dp(4), dp(10), dp(4))
        }
        serverInput = EditText(this).apply {
            setSingleLine(true)
            hint = "IP сервера:8098"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setTextColor(Color.WHITE)
            setHintTextColor(Color.LTGRAY)
            setText(prefs.getString("server", ""))
        }
        tokenInput = EditText(this).apply {
            setSingleLine(true)
            hint = "Код первого подключения"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setTextColor(Color.WHITE)
            setHintTextColor(Color.LTGRAY)
            setText(prefs.getString("token", ""))
        }
        settingsPanel.addView(serverInput, LinearLayout.LayoutParams(0, dp(58), 1f))
        settingsPanel.addView(tokenInput, LinearLayout.LayoutParams(0, dp(58), 1f))
        settingsPanel.addView(Button(this).apply {
            text = "Подключиться"
            setOnClickListener { loadCatalog() }
        })
        root.addView(settingsPanel)
        settingsPanel.visibility = if (prefs.getString("token", "").isNullOrEmpty()) View.VISIBLE else View.GONE

        val scroll = ScrollView(this).apply {
            isFillViewport = true
            clipToPadding = false
            setPadding(0, dp(12), 0, 0)
        }
        catalog = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 0, 0, dp(18))
        }
        scroll.addView(catalog)
        root.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        if (!prefs.getString("token", "").isNullOrEmpty()) {
            loadCatalog()
        } else {
            showMessage("Укажите адрес сервера и код один раз. Затем подключение будет автоматическим.")
        }
    }

    override fun onResume() {
        super.onResume()
        // Repaint resume badges after returning from playback, without losing selection.
        if (::catalog.isInitialized && catalog.childCount > 0 &&
            !prefs.getString("token", "").isNullOrEmpty()) loadCatalog()
    }

    private fun showMessage(message: String) {
        catalog.removeAllViews()
        catalog.addView(label(message, 19f, Color.rgb(180, 200, 218)))
    }

    private fun requestLibrary(base: String, key: String): JSONArray {
        val connection = URL(base + "/api/v1/library").openConnection() as HttpURLConnection
        connection.connectTimeout = 2200
        connection.readTimeout = 5000
        connection.setRequestProperty("X-DiscForge-Token", key)
        try {
            if (connection.responseCode != 200) {
                throw IllegalStateException("HTTP " + connection.responseCode + ". Проверьте код.")
            }
            val body = connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            return JSONObject(body).getJSONArray("items")
        } finally {
            connection.disconnect()
        }
    }

    private fun loadCatalog() {
        if (busy) return
        val base = ServerAddress.normalize(serverInput.text.toString())
        val key = tokenInput.text.toString().trim()
        if (base == null || key.length < 16) {
            settingsPanel.visibility = View.VISIBLE
            status.text = "Введите локальный IP сервера и код (не менее 16 символов)."
            return
        }
        busy = true
        status.text = "Подключение к домашней медиатеке…"
        worker.execute {
            var chosen: String = base
            var result: JSONArray? = null
            var failure: Exception? = null
            try {
                result = requestLibrary(base, key)
            } catch (exc: Exception) {
                failure = exc
                // UDP broadcasts carry NO token. Candidate servers are authenticated
                // via the same existing HTTP token before a new IP is accepted.
                for (candidate in LanDiscovery.discover(key)) {
                    if (candidate == base) continue
                    try {
                        result = requestLibrary(candidate, key)
                        chosen = candidate
                        break
                    } catch (_: Exception) { /* Not our paired server. */ }
                }
            }
            val items = result
            runOnUiThread {
                busy = false
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (items == null) {
                    status.text = "Сервер не найден: " + (failure?.message ?: "проверьте Wi-Fi")
                    settingsPanel.visibility = View.VISIBLE
                    return@runOnUiThread
                }
                serverInput.setText(chosen.removePrefix("http://"))
                prefs.edit().putString("server", chosen).putString("token", key).apply()
                settingsPanel.visibility = View.GONE
                status.text = "Подключено · " + chosen.removePrefix("http://") +
                    " · фильмов: " + items.length()
                renderLibrary(items, chosen, key)
            }
        }
    }

    private fun renderLibrary(items: JSONArray, base: String, token: String) {
        catalog.removeAllViews()
        val groups = linkedMapOf<String, MutableList<JSONObject>>()
        for (index in 0 until items.length()) {
            val item = items.optJSONObject(index) ?: continue
            val id = item.optString("id")
            if (!id.matches(Regex("[a-f0-9]{24}")) ||
                item.optString("url") != "/api/v1/media/" + id) continue
            val category = item.optString("category", "Фильмы")
                .take(45).ifBlank { "Фильмы" }
            groups.getOrPut(category) { mutableListOf() }.add(item)
        }
        if (groups.isEmpty()) {
            showMessage("Библиотека пуста. Добавьте MP4/MKV в папку сервера на Mac или NAS.")
            return
        }
        val firstCategory = groups.keys.first()
        for ((category, movies) in groups) {
            catalog.addView(label(category + "   ·   " + movies.size, 22f).apply {
                typeface = Typeface.DEFAULT_BOLD
                setPadding(0, dp(12), 0, dp(9))
            })
            for (item in movies) {
                val id = item.getString("id")
                val movieTitle = item.optString("title", "Фильм")
                val movieUrl = base + "/api/v1/media/" + id
                val bookmarkKey = WatchProgress.bookmarkKeyByToken(token, id)
                val bookmarked = playback.getLong(bookmarkKey,
                    playback.getLong(WatchProgress.bookmarkKey(base, id), 0L))
                val row = LinearLayout(this).apply {
                    gravity = Gravity.CENTER_VERTICAL
                    orientation = LinearLayout.HORIZONTAL
                    background = background()
                    setPadding(dp(9), dp(7), dp(9), dp(7))
                    isFocusable = true
                    isClickable = true
                    setOnFocusChangeListener { _, focused -> alpha = if (focused) 1f else 0.85f }
                    alpha = 0.85f
                    setOnClickListener {
                        startActivity(Intent(this@MainActivity, PlayerActivity::class.java).apply {
                            putExtra("url", movieUrl)
                            putExtra("token", token)
                            putExtra("title", movieTitle)
                        })
                    }
                }
                val image = ImageView(this).apply {
                    scaleType = ImageView.ScaleType.CENTER_CROP
                    setBackgroundColor(Color.rgb(49, 66, 86))
                    contentDescription = "Постер: " + movieTitle
                }
                row.addView(image, LinearLayout.LayoutParams(dp(118), dp(82)))
                val textColumn = LinearLayout(this).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(dp(18), 0, 0, 0)
                }
                textColumn.addView(label(movieTitle, 19f))
                if (WatchProgress.canResume(bookmarked)) {
                    textColumn.addView(label("▶ Продолжить с " +
                        WatchProgress.timeLabel(bookmarked), 14f, Color.rgb(115, 214, 192)))
                } else {
                    textColumn.addView(label("▶ Смотреть", 14f, Color.rgb(157, 185, 209)))
                }
                row.addView(textColumn, LinearLayout.LayoutParams(0,
                    ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                catalog.addView(row, LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(96)).apply {
                    bottomMargin = dp(7)
                })
                val poster = item.optString("poster")
                if (poster == "/api/v1/poster/" + id) {
                    fetchPoster(image, base + poster, token)
                }
            }
        }
        // D-pad focus stays on the first movie after the initial connection.
        if (catalog.childCount > 1) catalog.getChildAt(1).requestFocus()
    }

    private fun fetchPoster(view: ImageView, address: String, key: String) {
        worker.execute {
            val bitmap = try {
                val connection = URL(address).openConnection() as HttpURLConnection
                connection.connectTimeout = 2000
                connection.readTimeout = 3500
                connection.setRequestProperty("X-DiscForge-Token", key)
                try {
                    if (connection.responseCode != 200 ||
                        connection.contentLengthLong > 8 * 1024 * 1024) null
                    else {
                        val out = ByteArrayOutputStream()
                        connection.inputStream.use { input ->
                            val buffer = ByteArray(8192)
                            while (out.size() <= 8 * 1024 * 1024) {
                                val count = input.read(buffer)
                                if (count == -1) break
                                out.write(buffer, 0, count)
                            }
                        }
                        if (out.size() > 8 * 1024 * 1024) null
                        else {
                            val bytes = out.toByteArray()
                            val options = BitmapFactory.Options().apply { inSampleSize = 2 }
                            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
                        }
                    }
                } finally {
                    connection.disconnect()
                }
            } catch (_: Exception) { null }
            if (bitmap != null) runOnUiThread {
                if (!isDestroyed && view.isAttachedToWindow) view.setImageBitmap(bitmap)
            }
        }
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }
}
