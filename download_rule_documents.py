#!/usr/bin/env python3
import json
import re
import subprocess
from html import unescape
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "data" / "rule_documents.json"
RULES_DIR = ROOT / "data" / "rules"
WIKI_POST_RE = re.compile(r"bbs\.robomaster\.com/wiki/\d+/(\d+)")
VERSION_RE = re.compile(r"V(\d+(?:\.\d+)+)", re.IGNORECASE)


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


def version_key(value):
    match = VERSION_RE.search(value or "")
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def fetch_wiki_rule_links(source_url):
    match = WIKI_POST_RE.search(source_url or "")
    if not match:
        return []
    post_id = match.group(1)
    result = subprocess.run(
        [
            "curl",
            "-fsSL",
            "--compressed",
            "--max-time",
            "30",
            "-X",
            "POST",
            "-H",
            "Accept: application/json, text/plain, */*",
            f"https://bbs.robomaster.com/developers-server/rest/posts/info/{post_id}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    content = json.loads(result.stdout)["data"]["htmlContent"]
    links = []
    for href, label in re.findall(r'href="([^"]+\.pdf)"[^>]*>([^<]+\.pdf)</a>', content):
        href, label = unescape(href), unescape(label)
        version = VERSION_RE.search(label)
        if version:
            links.append({"url": quote(href, safe=":/?=&%"), "title": label, "version": f"V{version.group(1)}"})
    return links


def latest_link(links, title_fragment, major):
    candidates = [
        item for item in links
        if title_fragment in item["title"] and version_key(item["version"])[:1] == (major,)
    ]
    return max(candidates, key=lambda item: version_key(item["version"]), default=None)


def refresh_dynamic_sources(manifest):
    source_cache = {}

    def links_for(source):
        if source not in source_cache:
            source_cache[source] = fetch_wiki_rule_links(source)
        return source_cache[source]

    for season, rules in manifest.get("rmuc", {}).items():
        source = rules.get("source", "")
        if not WIKI_POST_RE.search(source):
            continue
        links = links_for(source)
        for phase, major in (("regional", 1), ("finals", 2)):
            selected = latest_link(links, "超级对抗赛比赛规则手册", major)
            if not selected:
                continue
            document = rules.setdefault(phase, {})
            old_version = document.get("version")
            document.update(version=selected["version"], remoteUrl=selected["url"])
            if old_version != selected["version"]:
                print(f"[new ] rmuc {season} {phase}: {old_version or '-'} -> {selected['version']}", flush=True)

    for season, document in manifest.get("rmul", {}).items():
        source = document.get("source", "")
        if not WIKI_POST_RE.search(source):
            continue
        selected = latest_link(links_for(source), "高校联盟赛比赛规则手册", 1)
        if not selected:
            continue
        old_version = document.get("version")
        document.update(version=selected["version"], remoteUrl=selected["url"])
        if old_version != selected["version"]:
            print(f"[new ] rmul {season}: {old_version or '-'} -> {selected['version']}", flush=True)


def validate_manifest(manifest):
    errors = []
    for event, season, phase, document in iter_documents(manifest):
        version = version_key(document.get("version"))
        expected_major = 1 if event == "rmul" or phase == "regional" else 2 if phase == "finals" else None
        if expected_major and version[:1] != (expected_major,):
            errors.append(f"{event} {season} {phase}: expected V{expected_major}.x, got {document.get('version')}")
        if not document.get("remoteUrl", "").startswith(("http://", "https://")):
            errors.append(f"{event} {season} {phase}: missing remote URL")
    if errors:
        raise RuntimeError("Rule manifest validation failed:\n- " + "\n- ".join(errors))


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
    try:
        refresh_dynamic_sources(manifest)
    except (subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"[warn] unable to refresh dynamic rule sources: {error}", flush=True)
    validate_manifest(manifest)

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
