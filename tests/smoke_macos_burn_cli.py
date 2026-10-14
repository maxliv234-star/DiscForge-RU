"""Hardware-free smoke test for the *packaged* macOS Blu-ray burner.

Only synthetic UDF 2.50 metadata are exercised. This neither records a disc
nor establishes UDF filesystem mountability or Blu-ray player compatibility.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Executed as "python tests/smoke_macos_burn_cli.py ..." from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_iso_udf_preflight import iso_fixture  # noqa: E402
from tools.iso_udf_preflight import SECTOR_SIZE  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: python tests/smoke_macos_burn_cli.py FROZEN_BINARY", file=sys.stderr)
        return 2
    binary = Path(args[0]).expanduser().resolve()
    if not binary.is_file():
        print(f"Frozen burner missing: {binary}", file=sys.stderr)
        return 2

    def invoke(*options: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(binary), *options], capture_output=True,
            text=True, timeout=45, check=False,
        )

    def expect(result: subprocess.CompletedProcess[str], code: int, phrase: str) -> None:
        output = result.stdout + result.stderr
        if result.returncode != code or phrase not in output:
            raise AssertionError(
                f"Frozen CLI exit={result.returncode}, expected={code}, "
                f"required={phrase!r}; stdout={result.stdout!r}; stderr={result.stderr!r}"
            )

    with tempfile.TemporaryDirectory(prefix="discforge-frozen-smoke-") as temp:
        good = Path(temp) / "valid.iso"
        bad = Path(temp) / "corrupt.iso"
        iso_fixture(good)
        shutil.copyfile(good, bad)
        # Invalid revision byte; also invalidates the LVD descriptor CRC.
        with bad.open("r+b") as handle:
            handle.seek(32 * SECTOR_SIZE + 240)
            handle.write(b"\x60")

        expect(invoke("check", str(good), "--profile", "BD25"), 0, "UDF 2.50")
        expect(invoke("check", str(good), "--profile", "BD50"), 0, "UDF 2.50")
        expect(invoke("burn", str(good), "--dry-run", "--profile", "BD25"),
               0, "Записи не выполнялось")
        expect(invoke("check", str(bad)), 1, "ОШИБКА:")
        expect(invoke("burn", str(bad), "--dry-run"), 1, "ОШИБКА:")
        expect(invoke("burn", str(good), "--yes"), 1, "--device")

    print("Frozen macOS burner: 6/6 hardware-free smoke cases passed.")
    print("No physical drive, mountable image, or Blu-ray player was tested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
