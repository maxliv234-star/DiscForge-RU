"""Conservative macOS native ISO burner.

Only burns an EXISTING image. No DRM processing, no image authoring, no GUI.
The actual optical drive and a rewritable disc are required for hardware tests.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from tools.iso_udf_preflight import CAPACITIES, inspect as inspect_udf


class MacBurnError(RuntimeError):
    """Failure to validate or burn an image."""


def validate_image(path: str | Path) -> Path:
    """Check elementary properties, NOT UDF/BDMV standard compliance."""
    try:
        image = Path(path).expanduser().resolve()
        if image.suffix.lower() != ".iso":
            raise MacBurnError("Нужен готовый образ .iso, а не папка BDMV или .dmg.")
        if not image.is_file():
            raise MacBurnError(f"Образ не найден: {image}")
        size = image.stat().st_size
    except (OSError, RuntimeError) as exc:
        # pathlib can raise RuntimeError for symlink loops on Python 3.11/3.12.
        # Reject malformed paths without leaking a traceback or starting a writer.
        raise MacBurnError(f"Не удалось прочитать ISO: {exc}") from exc
    if size == 0 or size % 2048:
        raise MacBurnError("Некорректный размер ISO: требуется ненулевое число секторов по 2048 байт.")
    return image


def _image_identity(image: Path) -> tuple[int, int, int, int, int]:
    """Detect routine concurrent ISO edits; this is not an atomic snapshot."""
    try:
        stat = image.stat()
    except OSError as exc:
        raise MacBurnError(f"ISO стал недоступен во время проверки: {exc}") from exc
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _require_unchanged(image: Path, fingerprint: tuple[int, int, int, int, int]) -> None:
    if _image_identity(image) != fingerprint:
        raise MacBurnError("ISO изменился во время проверки; запись остановлена. Повторите проверку.")


def _validated_image_with_identity(path: str | Path, *, profile: str | None = None,
                                   inspect_bdmv: bool = False) -> tuple[Path, tuple[int, int, int, int, int]]:
    """Keep the preflight fingerprint through the actual burn, without a fresh baseline."""
    try:
        original = Path(path).expanduser()
        if original.is_symlink():
            raise MacBurnError("Символическая ссылка на ISO запрещена перед записью.")
    except (OSError, RuntimeError) as exc:
        raise MacBurnError(f"Не удалось проверить путь ISO: {exc}") from exc
    image = validate_image(original)
    fingerprint = _image_identity(image)
    if profile is None:
        profile = "BD25" if fingerprint[2] <= CAPACITIES["BD25"] else "BD50"
    if profile not in CAPACITIES:
        raise MacBurnError("Для записи поддерживаются только профили BD25 и BD50.")
    try:
        report = inspect_udf(image, profile=profile)
    except (OSError, ValueError) as exc:
        # A read failure must be fatal before the writer is started.
        raise MacBurnError(f"Не удалось прочитать UDF 2.50 ISO: {exc}") from exc
    if not report.valid:
        raise MacBurnError(
            f"ISO не прошёл проверку UDF 2.50 ({profile}): " + "; ".join(report.errors)
        )
    if inspect_bdmv:
        # macOS only: read-only mount and structural BDMV inspection.
        # Remains opt-in pending tests on actual authored Blu-ray ISO images.
        from tools.macos_mounted_bdmv import MountedBDMVError, inspect_mounted_bdmv
        try:
            inspect_mounted_bdmv(image, profile=profile)
        except MountedBDMVError as exc:
            raise MacBurnError(str(exc)) from exc
    _require_unchanged(image, fingerprint)
    return image, fingerprint


def validate_for_burning(path: str | Path, *, profile: str | None = None,
                         inspect_bdmv: bool = False) -> Path:
    """Fail closed before touching a recorder; metadata preflight is not a playback test."""
    image, _ = _validated_image_with_identity(path, profile=profile, inspect_bdmv=inspect_bdmv)
    return image


def burn_command(image: Path, device: str | None = None, speed: int | None = None) -> list[str]:
    """Use Apple's image writer; keep original ISO rather than synthesize a new filesystem."""
    if speed is not None and (type(speed) is not int or speed < 1 or speed > 16):
        raise MacBurnError("Скорость записи должна быть целым числом 1–16.")
    command = [
        "hdiutil", "burn", str(image), "-verifyburn", "-forceclose",
        "-nosynthesize", "-noaddpmap", "-nooptimizeimage",
    ]
    if device is not None:
        # An explicitly supplied invalid drive must not silently fall back
        # to hdiutil's automatic selection (which may target another burner).
        if (not isinstance(device, str) or not device or
                device != device.strip() or device.startswith("-") or
                any(ord(char) < 32 or ord(char) == 127 for char in device)):
            raise MacBurnError("Недопустимый идентификатор привода.")
        command.extend(["-device", device])
    if speed is not None:
        command.extend(["-speed", str(speed)])
    return command


def require_macos() -> None:
    if sys.platform != "darwin":
        raise MacBurnError("Запись hdiutil доступна только на macOS.")


def list_drives() -> str:
    require_macos()
    try:
        completed = subprocess.run(["hdiutil", "burn", "-list"],
                                   capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MacBurnError(f"Не удалось получить список приводов: {exc}") from exc
    if completed.returncode != 0:
        raise MacBurnError(completed.stderr.strip() or "hdiutil не смог обнаружить приводы.")
    return completed.stdout


def burn(image: str | Path, *, device: str | None = None, speed: int | None = None,
         profile: str | None = None, inspect_bdmv: bool = False) -> None:
    require_macos()
    source, fingerprint = _validated_image_with_identity(
        image, profile=profile, inspect_bdmv=inspect_bdmv
    )
    command = burn_command(source, device=device, speed=speed)
    _require_unchanged(source, fingerprint)
    try:
        completed = subprocess.run(command, check=False)
    except OSError as exc:
        raise MacBurnError(f"Не удалось запустить hdiutil: {exc}") from exc
    if completed.returncode != 0:
        raise MacBurnError(f"Запись или проверка завершилась с ошибкой (код {completed.returncode}).")
    # hdiutil may report success after a source ISO changes during the write.
    # Such a disc cannot be treated as verified; keep the original fingerprint.
    _require_unchanged(source, fingerprint)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DiscForge RU: запись готового ISO на macOS")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("drives", help="Показать оптические приводы")
    check_parser = commands.add_parser("check", help="Проверить UDF 2.50 без записи")
    check_parser.add_argument("iso", help="Путь к ISO")
    check_parser.add_argument("--profile", choices=("BD25", "BD50"),
                              help="Проверить размер для конкретного носителя")
    check_parser.add_argument("--inspect-bdmv", action="store_true",
                              help="macOS: смонтировать ISO только для чтения и проверить BDMV")
    burn_parser = commands.add_parser("burn", help="Записать готовый ISO с проверкой")
    burn_parser.add_argument("iso", help="Путь к ISO")
    burn_parser.add_argument("--device", help="Обязательный для реальной записи идентификатор из hdiutil burn -list")
    burn_parser.add_argument("--speed", type=int, help="Скорость, например 2 или 4")
    burn_parser.add_argument("--profile", choices=("BD25", "BD50"),
                             help="Ограничить образ вместимостью выбранного носителя")
    burn_parser.add_argument("--dry-run", action="store_true", help="Не записывать диск")
    burn_parser.add_argument("--inspect-bdmv", action="store_true",
                             help="macOS: дополнительно проверить BDMV внутри смонтированного ISO")
    burn_parser.add_argument("--yes", action="store_true", help="Подтвердить запись на носитель")
    args = parser.parse_args(argv)
    try:
        if args.action == "drives":
            print(list_drives())
            return 0
        if args.action == "check":
            checked, fingerprint = _validated_image_with_identity(
                args.iso, profile=args.profile, inspect_bdmv=args.inspect_bdmv
            )
            _require_unchanged(checked, fingerprint)
            print("Предварительная проверка UDF 2.50 пройдена:", checked)
            if args.inspect_bdmv:
                print("Статическая проверка BDMV в смонтированном ISO пройдена.")
                print("Это НЕ проверка реального диска или совместимости плеера.")
            else:
                print("Это НЕ проверка структуры BDMV, записанного диска или совместимости плеера.")
            return 0
        if args.dry_run:
            image, fingerprint = _validated_image_with_identity(
                args.iso, profile=args.profile, inspect_bdmv=args.inspect_bdmv
            )
            command = burn_command(image, args.device, args.speed)
            _require_unchanged(image, fingerprint)
            print("Проверка UDF 2.50 пройдена. Будет выполнена команда:", repr(command))
            if args.inspect_bdmv:
                print("Статическая проверка BDMV пройдена. Записи не выполнялось.")
            else:
                print("Структура BDMV НЕ проверялась. Записи не выполнялось.")
            print("Совместимость с бытовым плеером НЕ проверялась.")
            return 0
        if not args.yes:
            raise MacBurnError("Для реальной записи добавьте --yes; сначала проверьте ISO и носитель.")
        if not args.device:
            raise MacBurnError(
                "Для реальной записи требуется явный --device из команды drives; "
                "автоматический выбор привода отключён в CLI."
            )
        print("Проверка ISO перед записью...")
        burn(args.iso, device=args.device, speed=args.speed, profile=args.profile,
             inspect_bdmv=args.inspect_bdmv)
        print("hdiutil сообщил об успешной записи и проверке. Совместимость плеера НЕ подтверждена.")
        return 0
    except MacBurnError as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
