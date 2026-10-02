import hashlib
import io
import tarfile
import zipfile

TOKEN = "s3cret-token-for-tests"
TOKEN_SHA = hashlib.sha256(TOKEN.encode()).hexdigest()
OTHER_TOKEN = "another-token"
OTHER_SHA = hashlib.sha256(OTHER_TOKEN.encode()).hexdigest()

ASSETS = {
    "boot.js": b"/* boot */",
    "client.css": b"/* css */",
    "client.js": b"/* client */",
    "game-worker.js": b"/* worker */",
}


def gameZip(assets=ASSETS, extra=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("src/game/main.py", "print('hi')\n")
        for name, data in assets.items():
            archive.writestr("src/tak/web/assets/" + name, data)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return out.getvalue()


def bundleFiles(version="1.0.0", index=None):
    return {
        "index.html": index or ("<html><title>v%s</title></html>" % version).encode(),
        "game.zip": gameZip(),
        "version.txt": (version + "\n").encode(),
    }


def tarBundle(files, prefix="", compression="", extra=()):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w" + (":" + compression if compression else "")) as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for info in extra:
            archive.addfile(info)
    return out.getvalue()


def zipBundle(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def registryText(entries):
    lines = ["games:"]
    for entry in entries:
        first = True
        for key, value in entry.items():
            prefix = "  - " if first else "    "
            first = False
            if isinstance(value, list):
                value = "[" + ", ".join(value) + "]"
            lines.append("%s%s: %s" % (prefix, key, value))
    if not entries:
        lines = ["games: []"]
    return "\n".join(lines) + "\n"


def game(slug="tidewater", token_sha256=TOKEN_SHA, **extra):
    entry = {
        "slug": slug,
        "title": slug.capitalize(),
        "repo": "Stephenson-Software/" + slug.capitalize(),
        "token_sha256": token_sha256,
    }
    entry.update(extra)
    return entry
