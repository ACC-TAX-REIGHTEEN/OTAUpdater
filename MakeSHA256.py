import hashlib
from pathlib import Path

zip_path = Path("main.zip")
output_path = Path("sha256.txt")

sha256 = hashlib.sha256()
with zip_path.open("rb") as f:
    for chunk in iter(lambda: f.read(8192), b""):
        sha256.update(chunk)

hash_value = sha256.hexdigest()
output_path.write_text(hash_value, encoding="ascii")

print(f"--> Berhasil membuat {output_path}: {hash_value}")
