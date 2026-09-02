from __future__ import annotations

import argparse
import os
import tempfile
import urllib.request
from pathlib import Path

from log_council.datasets.contracts import (
    DatasetError,
    DatasetFile,
    load_manifest,
    validate_dataset_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = {
    "loghub-openstack-2k": PROJECT_ROOT / "data" / "manifests" / "loghub-openstack-2k.json",
}


def download_file(spec: DatasetFile, destination: Path, force: bool = False) -> str:
    if destination.exists() and not force:
        validate_dataset_file(destination, spec)
        return "verified"

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        spec.url,
        headers={"User-Agent": "LogCouncil/0.1 dataset downloader"},
    )
    temporary_name: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, dir=destination.parent, prefix=f".{spec.name}."
            ) as temporary:
                temporary_name = temporary.name
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > spec.max_bytes:
                        raise DatasetError(
                            f"Download exceeded {spec.max_bytes} bytes for {spec.name}"
                        )
                    temporary.write(chunk)
        validate_dataset_file(temporary_name, spec)
        os.replace(temporary_name, destination)
        temporary_name = None
        return "downloaded"
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a pinned external log dataset.")
    parser.add_argument("dataset", choices=sorted(MANIFESTS))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest(MANIFESTS[args.dataset])
    target_dir = PROJECT_ROOT / "data" / "external" / manifest.dataset_id
    try:
        for spec in manifest.files:
            status = download_file(spec, target_dir / spec.name, args.force)
            print(f"{status}: {spec.name}")
    except (DatasetError, OSError) as exc:
        print(f"error: {exc}")
        return 1
    print(f"ready: {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
