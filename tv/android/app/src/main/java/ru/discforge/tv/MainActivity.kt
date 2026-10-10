package ru.discforge.tv

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var serverInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var status: TextView
    private lateinit var list: LinearLayout
    private var catalogRequest = 0
    private val prefs by lazy { getSharedPreferences("connection", MODE_PRIVATE) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(40, 25, 40, 25)
            setBackgroundColor(Color.rgb(13, 22, 37))
        }
        setContentView(root)
        root.addView(TextView(this).apply {
            text = "DISCFORGE TV     •     FULL HD"
            textSize = 27f
            setTextColor(Color.WHITE)
        })
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        serverInput = EditText(this).apply {
            setSingleLine(true)
            hint = "IP ПК: 192.168.1.100:8098"
            setText(prefs.getString("server", "192.168.1.100:8098"))
            setTextColor(Color.WHITE)
            setHintTextColor(Color.LTGRAY)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        }
        tokenInput = EditText(this).apply {
            setSingleLine(true)
            hint = "Код подключения с компьютера"
            setText(prefs.getString("token", ""))
            setTextColor(Color.WHITE)
            setHintTextColor(Color.LTGRAY)
            inputType = InputType.TYPE_CLASS_TEXT
        }
        row.addView(serverInput, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.2f))
        row.addView(tokenInput, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.5f))
        val connect = Button(this).apply {
            text = "Подключиться"
            setOnClickListener { loadCatalog() }
        }
        row.addView(connect)
        root.addView(row)
        status = TextView(this).apply {
            text = "ПК и телевизор должны находиться в одной домашней сети."
            textSize = 17f
            setTextColor(Color.LTGRAY)
        }
        root.addView(status)
        val scroll = ScrollView(this)
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        scroll.addView(list)
        root.addView(scroll, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        connect.requestFocus()
    }

    private fun loadCatalog() {
        val request = ++catalogRequest
        val base = ServerAddress.normalize(serverInput.text.toString())
        val key = tokenInput.text.toString().trim()
        if (base == null || key.length < 16) {
            status.text = "Введите локальный IP компьютера и код подключения (минимум 16 символов)."
            return
        }
        prefs.edit().putString("server", base).putString("token", key).apply()
        status.text = "Загружаю библиотеку…"
        list.removeAllViews()
        executor.execute {
            try {
                val connection = URL("$base/api/v1/library").openConnection() as HttpURLConnection
                connection.connectTimeout = 4000
                connection.readTimeout = 8000
                connection.setRequestProperty("X-DiscForge-Token", key)
                val response = try {
                    if (connection.responseCode != 200) {
                        throw IllegalStateException("HTTP " + connection.responseCode + ": проверьте адрес и код")
                    }
                    connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                } finally { connection.disconnect() }
                val items = JSONObject(response).getJSONArray("items")
                // Decode untrusted JSON on the worker, inside the error handler.
                // Exceptions posted to the UI thread cannot be caught here.
                val entries = (0 until items.length()).mapNotNull { index ->
                    val item = items.getJSONObject(index)
                    val id = item.getString("id")
                    val path = item.getString("url")
                    val title = item.getString("title")
                    if (id.matches(Regex("[a-f0-9]{24}")) && path == "/api/v1/media/$id") {
                        title to path
                    } else null
                }
                runOnUiThread {
                    if (isFinishing || isDestroyed || request != catalogRequest) return@runOnUiThread
                    status.text = "В библиотеке фильмов: " + entries.size
                    if (entries.isEmpty()) {
                        list.addView(TextView(this).apply {
                            text = "Добавьте MP4/MKV в папку медиасервера на ПК."
                            setTextColor(Color.WHITE)
                            textSize = 20f
                        })
                    }
                    for ((title, path) in entries) {
                        list.addView(Button(this).apply {
                            text = "▶  $title"
                            isFocusable = true
                            textSize = 20f
                            setOnClickListener {
                                startActivity(Intent(this@MainActivity, PlayerActivity::class.java).apply {
                                    putExtra("url", base + path)
                                    putExtra("token", key)
                                    putExtra("title", title)
                                })
                            }
                        })
                    }
                }
            } catch (exc: Exception) {
                runOnUiThread {
                    if (!isFinishing && !isDestroyed && request == catalogRequest) {
                        status.text = "Ошибка подключения: " + exc.message
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }
}
