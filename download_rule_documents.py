#!/usr/bin/env python3
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "data" / "rule_documents.json"
RULES_DIR = ROOT / "data" / "rules"


def filename_for(event, season, phase, version):
    version_slug = re.sub(r"[^0-9A-Za-z]+", "-", version).strip("-").lower()
    parts = [event, season]
    if phase:
        parts.append(phase)
    parts.append(version_slug)
    return "-".join(parts) + ".pdf"


def download_pdf(url, destination):
    if destination.exists() and destination.read_bytes()[:5] == b"%PDF-":
        print(f"[skip] {destination.name}", flush=True)
        return

    temporary = destination.with_suffix(".pdf.part")
    print(f"[get ] {destination.name}", flush=True)
    subprocess.run(
        [
            "curl",
            "-fL",
            "--retry",
            "3",
            "--connect-timeout",
            "20",
            "--max-time",
            "180",
            "--output",
            str(temporary),
            url,
        ],
        check=True,
    )
    if temporary.read_bytes()[:5] != b"%PDF-":
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded file is not a PDF: {url}")
    temporary.replace(destination)
    print(f"[done] {destination.name}", flush=True)


def iter_documents(manifest):
    for season, season_rules in manifest.get("rmuc", {}).items():
        for phase in ("default", "regional", "finals"):
            document = season_rules.get(phase)
            if document:
                yield "rmuc", season, phase, document
    for season, document in manifest.get("rmul", {}).items():
        yield "rmul", season, "", document


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    RULES_DIR.mkdir(parents=True, exist_ok=True)

    for event, season, phase, document in iter_documents(manifest):
        remote_url = document.get("remoteUrl") or document.get("url", "")
        if not remote_url.startswith(("http://", "https://")):
            raise RuntimeError(f"Missing remote URL for {event} {season} {phase}")
        filename = filename_for(event, season, phase, document["version"])
        download_pdf(remote_url, RULES_DIR / filename)
        document["remoteUrl"] = remote_url
        document["url"] = f"rules/{filename}"

    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {MANIFEST_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
