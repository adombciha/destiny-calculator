"""Download only the pinned official ephemeris files listed by the package."""

from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    manifest = json.loads(
        files("destiny_calculator")
        .joinpath("data/ephemeris_manifest.json")
        .read_text(encoding="utf-8")
    )
    directory = Path(__file__).resolve().parents[1] / "data" / "ephemeris"
    directory.mkdir(parents=True, exist_ok=True)
    for entry in manifest["files"]:
        target = directory / entry["name"]
        if target.exists():
            data = target.read_bytes()
        else:
            with urlopen(entry["url"], timeout=60) as response:
                data = response.read()
        if len(data) != entry["size_bytes"] or sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"Checksum mismatch for {target.name}; no file was overwritten.")
        if not target.exists():
            with target.open("xb") as output:
                output.write(data)
        print(f"Verified {target.name}: {entry['sha256']}")


if __name__ == "__main__":
    main()
