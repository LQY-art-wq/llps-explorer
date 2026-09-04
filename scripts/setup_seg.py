"""Install the pinned NCBI segmasker subset without changing PATH or running it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import posixpath
import shutil
import stat
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "external" / "seg-source.json"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_SELECTED_BYTES = 256 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
OFFICIAL_HOST = "ftp.ncbi.nlm.nih.gov"


class InstallError(ValueError):
    """A failed integrity, ownership, or archive-layout check."""


def official_url(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != OFFICIAL_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise InstallError("Downloads must use the official NCBI HTTPS host.")
    return url


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def hashes(path: Path) -> dict[str, str]:
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            md5.update(chunk)
            sha256.update(chunk)
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}


def reject_links(path: Path) -> None:
    """Do not write through a symbolic link or Windows reparse-point ancestor."""
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        reparse = getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        )
        if stat.S_ISLNK(info.st_mode) or reparse:
            raise InstallError("Installation paths must not traverse links or reparse points.")


def select_platform(requested: str) -> str:
    if requested != "auto":
        return requested
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise InstallError("Automatic installation supports x86-64 Windows and Linux only.")
    if sys.platform == "win32":
        return "windows-x64"
    if sys.platform.startswith("linux"):
        return "linux-x64"
    raise InstallError("Select a supported target platform explicitly.")


def verify_archive(path: Path, package: dict) -> dict[str, str]:
    if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise InstallError("The archive is absent, not a regular file, or exceeds 512 MiB.")
    actual = hashes(path)
    if actual["md5"] != package["official_archive_md5"]:
        raise InstallError("Archive MD5 differs from the pinned official checksum.")
    expected_sha256 = package.get("archive_sha256")
    if expected_sha256 is not None and actual["sha256"] != expected_sha256:
        raise InstallError("Archive SHA256 differs from the audited package.")
    return actual


def download_archive(path: Path, package: dict) -> None:
    """Use verified TLS and an exclusive cache file; never replace an existing cache."""
    reject_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = build_opener(OfficialRedirects())
    checksum_url = official_url(package["checksum_url"])
    with opener.open(Request(checksum_url), timeout=30) as response:
        checksum = response.read(65537)
    if len(checksum) > 65536:
        raise InstallError("The published checksum response exceeds its size limit.")
    fields = checksum.decode("ascii").split()
    if (
        len(fields) != 2
        or fields[0].lower() != package["official_archive_md5"]
        or fields[1].lstrip("*") != package["archive_filename"]
    ):
        raise InstallError("The current official checksum does not match the pinned release.")
    with tempfile.TemporaryDirectory(prefix=".seg-download-", dir=path.parent) as temporary:
        staged = Path(temporary) / package["archive_filename"]
        request = Request(
            official_url(package["source_url"]),
            headers={"User-Agent": "LLPS-Explorer-SEG-Installer/0.3"},
        )
        with opener.open(request, timeout=30) as response, staged.open("xb") as handle:
            total = 0
            while chunk := response.read(CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise InstallError("The archive response exceeds 512 MiB.")
                handle.write(chunk)
        verify_archive(staged, package)
        with staged.open("rb") as source, path.open("xb") as target:
            shutil.copyfileobj(source, target, CHUNK_BYTES)


def archive_name(name: str, archive_root: str) -> str:
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or "\\" in name
        or ":" in name
        or ".." in path.parts
        or not path.parts
        or path.parts[0] != archive_root
    ):
        raise InstallError("An archive member is outside the pinned package root.")
    return path.as_posix()


def wanted(name: str, executable: str, target_platform: str) -> bool:
    parts = PurePosixPath(name).parts
    leaf = parts[-1].lower()
    if name == executable:
        return True
    if leaf.startswith(("license", "readme", "notice", "copying", "blast_privacy")):
        return True
    if len(parts) < 3 or parts[1] not in {"bin", "lib", "lib64"}:
        return False
    if target_platform == "windows-x64":
        return leaf.endswith(".dll")
    return leaf.endswith(".so") or ".so." in leaf


def regular_target(
    name: str, members: dict[str, tarfile.TarInfo], archive_root: str
) -> tarfile.TarInfo:
    """Materialize internal library links as bytes, never create filesystem links."""
    visited = set()
    while True:
        if name in visited or name not in members:
            raise InstallError("An archive link is cyclic or outside the selected file set.")
        visited.add(name)
        item = members[name]
        if item.isfile():
            return item
        if not (item.issym() or item.islnk()):
            raise InstallError("Selected archive members must be files or internal file links.")
        link = item.linkname
        if PurePosixPath(link).is_absolute() or "\\" in link or ":" in link:
            raise InstallError("Archive links must stay inside the selected package files.")
        base = str(PurePosixPath(name).parent) if item.issym() else ""
        name = archive_name(posixpath.normpath(posixpath.join(base, link)), archive_root)


def install_subset(
    archive: Path, destination: Path, package: dict, target_platform: str
) -> tuple[list[dict], int]:
    archive_root = package["archive_root"]
    executable = package["executable_relative_path"]
    reject_links(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as bundle:
        members = {}
        case_names = set()
        for member in bundle:
            name = archive_name(member.name, archive_root)
            if member.isdir() or not wanted(name, executable, target_platform):
                continue
            key = name.lower() if target_platform == "windows-x64" else name
            if key in case_names:
                raise InstallError("The archive contains duplicate selected file names.")
            case_names.add(key)
            members[name] = member
        required = {executable, *(f"{archive_root}/{x}" for x in ("LICENSE", "README"))}
        if not required.issubset(members):
            raise InstallError("The archive does not contain segmasker and its required notices.")
        targets = {name: regular_target(name, members, archive_root) for name in members}
        if any(item.size < 0 for item in targets.values()) or (
            sum(item.size for item in targets.values()) > MAX_SELECTED_BYTES
        ):
            raise InstallError("Selected archive files exceed 256 MiB after resolving links.")
        with tempfile.TemporaryDirectory(prefix=".seg-stage-", dir=destination) as temporary:
            staged_root = Path(temporary)
            records = []
            for name, member in targets.items():
                staged = staged_root / name
                staged.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise InstallError("A selected archive file could not be read.")
                with source, staged.open("xb") as handle:
                    shutil.copyfileobj(source, handle, CHUNK_BYTES)
                if staged.stat().st_size != member.size:
                    raise InstallError("A selected archive file has been truncated.")
                record = {"member": name, "bytes": staged.stat().st_size, **hashes(staged)}
                if name == executable and package.get("executable_sha256") is not None:
                    if record["sha256"] != package["executable_sha256"]:
                        raise InstallError("Extracted executable SHA256 differs from the audit.")
                records.append(record)
            # Check every existing selected path before creating any installed file.
            for record in records:
                target = destination / record["member"]
                reject_links(target)
                if target.exists() and (
                    not target.is_file() or hashes(target)["sha256"] != record["sha256"]
                ):
                    raise InstallError(
                        "An existing installation differs; choose a different --destination."
                    )
                if (
                    target.exists()
                    and target_platform == "linux-x64"
                    and record["member"] == executable
                    and not os.access(target, os.X_OK)
                ):
                    raise InstallError("The existing Linux executable lacks execute permission.")
            created = 0
            for record in records:
                target = destination / record["member"]
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with (
                    (staged_root / record["member"]).open("rb") as source,
                    target.open("xb") as out,
                ):
                    shutil.copyfileobj(source, out, CHUNK_BYTES)
                if target_platform == "linux-x64":
                    target.chmod(0o755 if record["member"] == executable else 0o644)
                created += 1
    return records, created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform", choices=("auto", "windows-x64", "linux-x64"), default="auto"
    )
    parser.add_argument("--destination", type=Path, default=ROOT / ".tools" / "seg")
    parser.add_argument("--archive", type=Path, help="Reuse a locally downloaded official archive.")
    parser.add_argument("--offline", action="store_true", help="Never download a missing archive.")
    args = parser.parse_args()
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        target_platform = select_platform(args.platform)
        package = manifest["platforms"][target_platform]
        destination = args.destination.expanduser().absolute()
        archive = (
            args.archive.expanduser().absolute()
            if args.archive is not None
            else destination / "downloads" / package["archive_filename"]
        )
        cached = archive.exists()
        if not cached:
            if args.offline or args.archive is not None:
                raise InstallError("No local archive is available; download is disabled.")
            download_archive(archive, package)
        actual = verify_archive(archive, package)
        records, created = install_subset(archive, destination, package, target_platform)
        executable = destination / package["executable_relative_path"]
        print(json.dumps({
            "status": "installed" if created else "already_verified",
            "platform": target_platform,
            "distribution_version": manifest["distribution_version"],
            "cache_reused": cached,
            "network_used": not cached,
            "archive_md5": actual["md5"],
            "archive_sha256": actual["sha256"],
            "executable_path": str(executable),
            "files_created": created,
            "selected_files": records,
            "executable_run": False,
            "path_modified": False,
        }, indent=2))
        return 0
    except (InstallError, OSError, ValueError, tarfile.TarError, KeyError) as error:
        print(f"SEG setup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
