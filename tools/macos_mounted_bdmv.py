"""Opt-in, read-only BDMV inspection of a mounted Blu-ray ISO on macOS.

UDF metadata validation alone cannot verify BDMV directory contents. This
additional check asks macOS to mount the existing image read-only, uses the
project's structural BDMV validator, and detaches before returning. It needs
macOS but neither an optical drive nor a blank disc. It is NOT a player test.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import tempfile

from bdmv_preflight import inspect as inspect_bdmv


class MountedBDMVError(RuntimeError):
    """Read-only mount, structural inspection or cleanup failed."""


@contextmanager
def _temporary_mountpoint():
    """Do not recursively remove a mounted ISO if detach fails."""
    try:
        mountpoint = Path(tempfile.mkdtemp(prefix="discforge-bdmv-check-"))
    except (OSError, RuntimeError) as exc:
        raise MountedBDMVError(
            f"Не удалось создать временную точку монтирования ISO: {exc}"
        ) from exc
    try:
        yield mountpoint
    finally:
        # An empty mountpoint can be removed safely. A still-mounted UDF
        # filesystem must never be traversed by TemporaryDirectory.rmtree.
        try:
            mountpoint.rmdir()
        except OSError:
            pass


def _detach_mount(mountpoint: Path) -> None:
    """Bounded non-forced hdiutil detach."""
    try:
        detached = subprocess.run(
            ["hdiutil", "detach", str(mountpoint)],
            capture_output=True, text=True, errors="replace", timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MountedBDMVError(
            f"Не удалось отключить проверочный том ISO {mountpoint}: {exc}"
        ) from exc
    if detached.returncode != 0:
        reason = (detached.stderr or detached.stdout or "hdiutil detach завершился с ошибкой").strip()
        raise MountedBDMVError(
            f"Не удалось отключить проверочный том ISO {mountpoint}: {reason[:500]}"
        )


def _cleanup_partial_attach(mountpoint: Path) -> None:
    """A failed/timed-out attach can nevertheless leave a mounted volume."""
    try:
        mounted = mountpoint.is_mount()
    except (OSError, RuntimeError) as exc:
        raise MountedBDMVError(
            f"Не удалось проверить состояние точки монтирования {mountpoint}: {exc}"
        ) from exc
    if mounted:
        try:
            _detach_mount(mountpoint)
        except MountedBDMVError as exc:
            raise MountedBDMVError(
                f"Проверочный том мог остаться смонтированным по адресу {mountpoint}: {exc}"
            ) from exc


def inspect_mounted_bdmv(image: str | Path, *, profile: str) -> None:
    """Fail closed on invalid BDMV content or incomplete ISO unmount.

    The caller must first perform UDF 2.50 and profile-size checks. No media
    writing, automatic filesystem repair, destructive detach or DVD/UHD paths.
    """
    if sys.platform != "darwin":
        raise MountedBDMVError("Проверка смонтированного ISO доступна только на macOS.")
    if profile not in ("BD25", "BD50"):
        raise MountedBDMVError("Поддерживаются только BD25 и BD50.")

    with _temporary_mountpoint() as mountpoint:
        try:
            attached = subprocess.run(
                ["hdiutil", "attach", "-readonly", "-nobrowse",
                 "-mountpoint", str(mountpoint), str(image)],
                capture_output=True, text=True, errors="replace", timeout=120, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _cleanup_partial_attach(mountpoint)
            raise MountedBDMVError(f"Не удалось смонтировать ISO только для чтения: {exc}") from exc
        if attached.returncode != 0:
            reason = (attached.stderr or attached.stdout or "hdiutil attach завершился с ошибкой").strip()
            _cleanup_partial_attach(mountpoint)
            raise MountedBDMVError(f"ISO не смонтирован: {reason[:500]}")

        validation_error = None
        try:
            try:
                report = inspect_bdmv(mountpoint, profile=profile)
                if not report.structurally_valid:
                    reasons = "; ".join(report.errors[:8]) or "структура BDMV не прошла проверку"
                    raise MountedBDMVError(f"Ошибка структуры BDMV внутри ISO: {reasons}")
            except (OSError, ValueError, RuntimeError) as exc:
                validation_error = exc
        finally:
            # Incomplete cleanup blocks burn; never use -force.
            _detach_mount(mountpoint)
        if validation_error is not None:
            raise MountedBDMVError(str(validation_error)) from validation_error
