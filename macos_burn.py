"""Conservative macOS native ISO burner.

Only burns an EXISTING image. No DRM processing, no image authoring, no GUI.
The actual optical drive and a rewritable disc are required for hardware tests.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


class MacBurnError(RuntimeError):
    """Failure to validate or burn an image."""


def validate_image(path: str | Path) -> Path:
    """Check elementary properties, NOT UDF/BDMV standard compliance."""
    image = Path(path).expanduser().resolve()
    if image.suffix.lower() != ".iso":
        raise MacBurnError("Нужен готовый образ .iso, а не папка BDMV или .dmg.")
    if not image.is_file():
        raise MacBurnError(f"Образ не найден: {image}")
    size = image.stat().st_size
    if size == 0 or size % 2048:
        raise MacBurnError("Некорректный размер ISO: требуется ненулевое число секторов по 2048 байт.")
    return image


def burn_command(image: Path, device: str | None = None, speed: int | None = None) -> list[str]:
    """Use Apple's image writer; keep original ISO rather than synthesize a new filesystem."""
    if speed is not None and (not isinstance(speed, int) or speed < 1 or speed > 16):
        raise MacBurnError("Скорость записи должна быть целым числом 1–16.")
    command = [
        "hdiutil", "burn", str(image), "-verifyburn", "-forceclose",
        "-nosynthesize", "-noaddpmap", "-nooptimizeimage",
    ]
    if device:
        if not device.strip() or device.startswith("-"):
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


def burn(image: str | Path, *, device: str | None = None, speed: int | None = None) -> None:
    require_macos()
    source = validate_image(image)
    command = burn_command(source, device=device, speed=speed)
    try:
        completed = subprocess.run(command, check=False)
    except OSError as exc:
        raise MacBurnError(f"Не удалось запустить hdiutil: {exc}") from exc
    if completed.returncode != 0:
        raise MacBurnError(f"Запись или проверка завершилась с ошибкой (код {completed.returncode}).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DiscForge RU: запись готового ISO на macOS")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("drives", help="Показать оптические приводы")
    burn_parser = commands.add_parser("burn", help="Записать готовый ISO с проверкой")
    burn_parser.add_argument("iso", help="Путь к ISO")
    burn_parser.add_argument("--device", help="Идентификатор из hdiutil burn -list")
    burn_parser.add_argument("--speed", type=int, help="Скорость, например 2 или 4")
    burn_parser.add_argument("--dry-run", action="store_true", help="Не записывать диск")
    burn_parser.add_argument("--yes", action="store_true", help="Подтвердить запись на носитель")
    args = parser.parse_args(argv)
    try:
        if args.action == "drives":
            print(list_drives())
            return 0
        image = validate_image(args.iso)
        command = burn_command(image, args.device, args.speed)
        if args.dry_run:
            print("Будет выполнена команда:", repr(command))
            print("ВНИМАНИЕ: это не проверка UDF 2.50/BDMV и не реальная запись.")
            return 0
        if not args.yes:
            raise MacBurnError("Для реальной записи добавьте --yes; сначала проверьте ISO и носитель.")
        print("Запись ISO и проверка на устройстве. Не отключайте привод до завершения.")
        burn(image, device=args.device, speed=args.speed)
        print("hdiutil сообщил об успешной записи и проверке. Совместимость плеера НЕ подтверждена.")
        return 0
    except MacBurnError as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
