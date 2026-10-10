"""Fetch one digest-pinned CI artifact and reject unsafe archive members."""

import argparse
import hashlib
import io
import os
import re
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path


class ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        url = urllib.parse.urlsplit(new_url)
        if (
            url.scheme != "https"
            or url.port not in (None, 443)
            or url.username
            or url.password
            or url.hostname
            not in {
                "api.github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
        ):
            raise ValueError("Artifact redirect origin refused")
        redirected = super().redirect_request(request, fp, code, message, headers, new_url)
        if url.hostname != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected


def fetch(asset_id: int, digest: str, destination: Path):
    if destination.exists():
        raise ValueError("Cache destination already exists")
    request = urllib.request.Request(
        f"https://api.github.com/repos/bitcoinuniverseio/btc_stamps/releases/assets/{asset_id}",
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/octet-stream",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "btc-stamps-curated-cache",
        },
    )
    opener = urllib.request.build_opener(ArtifactRedirect())
    with opener.open(request, timeout=30) as response:
        raw = response.read(101_335_725)
    if len(raw) != 101_335_724 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Curated artifact size/digest mismatch")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        names = [member.name.rstrip("/") for member in members]
        if len(names) != 80 or len(set(names)) != 80:
            raise ValueError("Curated artifact membership mismatch")
        total = 0
        for member in members:
            name = member.name.rstrip("/")
            if name == "blocks" and member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Curated artifact contains a link/special entry")
            if name == "capture-receipt.json" and 0 < member.size <= 65_536:
                continue
            if not re.fullmatch(r"blocks/[0-9a-f]{64}\.bin", name) or not 81 <= member.size <= 4_194_304:
                raise ValueError("Curated artifact path/size refused")
            total += member.size
        if total != 135_905_865 or "capture-receipt.json" not in names or "blocks" not in names:
            raise ValueError("Curated artifact total size/layout mismatch")
        destination.mkdir(parents=True)
        (destination / "blocks").mkdir()
        for member in members:
            if member.isdir():
                continue
            stream = archive.extractfile(member)
            with stream:
                data = stream.read(member.size + 1)
            if len(data) != member.size:
                raise ValueError("Curated archive member truncated")
            with (destination / member.name).open("xb") as output:
                output.write(data)
    print("Downloaded digest-pinned 78-block CI cache")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-id", type=int, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    fetch(args.asset_id, args.sha256, args.destination)
