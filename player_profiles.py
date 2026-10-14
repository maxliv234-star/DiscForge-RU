"""Optional conservative encoding targets for physical Blu-ray-player testing.

These are *experimental DiskForge authoring choices*, NOT vendor limits or proof
that any player accepts unsigned BD-J Xlets on recorded BD-R/BD-RE.
"""
from __future__ import annotations

PLAYER_PROFILES = {
    "universal": "Универсальный Blu-ray",
    "giec-g2805": "GIEC BDP-G2805 (экспериментальный)",
}
G2805_VIDEO_AVERAGE_TARGET = 24_000_000
G2805_VIDEO_PEAK_TARGET = 26_000_000
G2805_COMBINED_PEAK_TARGET = 32_000_000
G2805_MUX_RESERVE = 1_000_000


def encode_targets(profile: str, requested_video_bps: int, audio_peak_bps: int) -> tuple[int, int | None]:
    """Return video average + optional VBV peak target without silent magic.

    Caller must log if average is reduced. Peak is a conservative *test*
    target, not a documented hardware decoding ceiling.
    """
    if profile not in PLAYER_PROFILES:
        raise ValueError("Неизвестный профиль проигрывателя.")
    if not isinstance(requested_video_bps, int) or requested_video_bps <= 0:
        raise ValueError("Некорректный видеобитрейт.")
    if not isinstance(audio_peak_bps, int) or audio_peak_bps < 0:
        raise ValueError("Некорректный битрейт звука.")
    if profile == "universal":
        return requested_video_bps, None
    peak = min(G2805_VIDEO_PEAK_TARGET,
               G2805_COMBINED_PEAK_TARGET - G2805_MUX_RESERVE - audio_peak_bps)
    average = min(requested_video_bps, G2805_VIDEO_AVERAGE_TARGET, peak)
    if average < 5_000_000:
        raise ValueError(
            "Для экспериментального режима GIEC G2805 выбран слишком большой "
            "суммарный аудиобитрейт. Уменьшите число дорожек или выберите AC-3."
        )
    return average, peak
