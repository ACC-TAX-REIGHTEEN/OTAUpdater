import os
import sys
import time
import shutil
import hashlib
import zipfile
import logging
import tempfile
import threading
import subprocess
import urllib.request
import urllib.error
import configparser
import importlib.util
import importlib.metadata
from collections import OrderedDict

DAPUR_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DAPUR_DIR)
OTA_DIR = os.path.join(DAPUR_DIR, "OTA")
LOCAL_ZIP_PATH = os.path.join(OTA_DIR, "main.zip")
OTA_CONF_PATH = os.path.join(OTA_DIR, "ota.conf")
OTA_LOG_PATH = os.path.join(OTA_DIR, "ota.log")

os.makedirs(OTA_DIR, exist_ok=True)

logger = logging.getLogger("EnterpriseOTA")
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = logging.FileHandler(OTA_LOG_PATH, encoding="utf-8")
    log_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)


class CLISpinner:

    def __init__(self, message="Memeriksa status sistem"):
        self.message = message
        self.running = False
        self.thread = None
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def _animate(self):
        idx = 0
        while self.running:
            frame = self.frames[idx % len(self.frames)]
            sys.stdout.write(f"\r{frame} {self.message}... ")
            sys.stdout.flush()
            time.sleep(0.1)
            idx += 1

    def update_message(self, new_message):
        sys.stdout.write("\r" + " " * (len(self.message) + 30) + "\r")
        self.message = new_message

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()

    def stop(self, final_message=None):
        self.running = False
        if self.thread:
            self.thread.join()
        sys.stdout.write("\r" + " " * (len(self.message) + 35) + "\r")
        if final_message:
            print(f"--> {final_message}")
        sys.stdout.flush()


def calculate_sha256(filepath):
    if not filepath or not os.path.exists(filepath) or not os.path.isfile(filepath):
        return None
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest().lower()


def parse_csv_list(raw_str):
    if not raw_str:
        return []
    return [item.strip() for item in raw_str.split(",") if item.strip()]


def load_ota_conf(conf_path):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str
    if os.path.exists(conf_path):
        cfg.read(conf_path, encoding="utf-8")

    dynamic_upgrades = []
    if cfg.has_section("PIP"):
        for key, val in cfg.items("PIP"):
            key_lower = key.strip().lower()
            val_clean = val.strip().lower()
            if key_lower.startswith("upgrade_") and key_lower != "upgrade_packages":
                if val_clean in ("ya", "true", "yes", "1"):
                    pkg_name = key.strip()[len("upgrade_"):].strip()
                    if pkg_name:
                        dynamic_upgrades.append(pkg_name)

        explicit_upgrades = parse_csv_list(cfg.get("PIP", "upgrade_packages", fallback=""))
        for pkg in explicit_upgrades:
            if pkg.lower() not in [p.lower() for p in dynamic_upgrades]:
                dynamic_upgrades.append(pkg)

    return {
        "zip_url": cfg.get("SETTINGS", "zip_url", fallback="").strip(),
        "hash_url": cfg.get("SETTINGS", "hash_url", fallback="").strip(),
        "timeout": cfg.getint("SETTINGS", "timeout", fallback=20),
        "orchestrator": cfg.get("SETTINGS", "orchestrator_script", fallback="").strip(),
        "protect_files": parse_csv_list(cfg.get("PROTECT", "files", fallback="credentials.json")),
        "backup_files": parse_csv_list(cfg.get("BACKUP", "files", fallback="")),
        "delete_files": parse_csv_list(cfg.get("DELETE", "files", fallback="")),
        "merge_confs": parse_csv_list(cfg.get("MERGE_CONF", "files", fallback="config.conf, piutang.conf")),
        "pip_packages": parse_csv_list(cfg.get("PIP", "packages", fallback="")),
        "pip_upgrades": dynamic_upgrades,
    }


def fetch_remote_hash(hash_url, timeout=20):
    req = urllib.request.Request(
        hash_url,
        headers={
            "User-Agent": "Enterprise-OTA-Updater/2.0",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="ignore").strip()
        if text:
            return text.split()[0].lower()
    return None


def download_file_with_timeout(url, dest_path, timeout=20):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Enterprise-OTA-Updater/2.0",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )
    start_time = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest_path, "wb") as out_file:
        while True:
            if time.monotonic() - start_time > timeout:
                raise TimeoutError(f"Unduhan melewati batas waktu ({timeout} detik).")
            chunk = resp.read(32768)
            if not chunk:
                break
            out_file.write(chunk)


def is_package_installed(pkg_name):
    try:
        importlib.metadata.distribution(pkg_name)
        return True
    except (importlib.metadata.PackageNotFoundError, ValueError):
        pass

    module_mapping = {
        "python-calamine": "calamine",
        "pillow": "PIL",
        "beautifulsoup4": "bs4",
        "scikit-learn": "sklearn",
        "pyyaml": "yaml",
    }
    import_name = module_mapping.get(pkg_name.lower(), pkg_name.replace("-", "_"))
    return importlib.util.find_spec(import_name) is not None


def handle_pip_operations(conf, is_ota_update_triggered=False, spinner=None):
    timeout = conf.get("timeout", 20)
    packages_to_ensure = conf.get("pip_packages", [])
    packages_to_upgrade = conf.get("pip_upgrades", [])

    for pkg in packages_to_ensure:
        if not is_package_installed(pkg):
            if spinner:
                spinner.update_message(f"Memasang modul Python yang dibutuhkan: {pkg}")
            logger.info(f"[PIP] Memasang modul baru: {pkg}")
            cmd = [
                sys.executable, "-m", "pip", "install", pkg,
                "--quiet", "--disable-pip-version-check", f"--default-timeout={timeout}"
            ]
            try:
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode == 0:
                    logger.info(f"[PIP] Berhasil memasang: {pkg}")
                else:
                    logger.warning(f"[PIP] Gagal memasang {pkg}: {res.stderr.strip()}")
            except Exception as e:
                logger.error(f"[PIP] Kesalahan saat instalasi {pkg}: {e}")

    if is_ota_update_triggered and packages_to_upgrade:
        sorted_upgrades = sorted(
            packages_to_upgrade, key=lambda x: 0 if x.lower() == "pip" else 1
        )
        for pkg in sorted_upgrades:
            if spinner:
                spinner.update_message(f"Memperbarui modul Python: {pkg}")
            logger.info(f"[PIP] Menjalankan: python -m pip install --upgrade {pkg}")
            cmd = [
                sys.executable, "-m", "pip", "install", "--upgrade", pkg,
                "--quiet", "--disable-pip-version-check", f"--default-timeout={timeout}"
            ]
            try:
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode == 0:
                    logger.info(f"[PIP] Modul {pkg} berhasil diperbarui.")
                else:
                    logger.warning(f"[PIP] Peringatan saat upgrade {pkg}: {res.stderr.strip()}")
            except Exception as e:
                logger.error(f"[PIP] Kesalahan saat upgrade {pkg}: {e}")


def parse_conf_sections(filepath):
    sections = OrderedDict()
    current_sec = "__GLOBAL__"
    sections[current_sec] = OrderedDict()

    if not os.path.exists(filepath):
        return sections

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                current_sec = stripped[1:-1].strip()
                if current_sec not in sections:
                    sections[current_sec] = OrderedDict()
            elif "=" in stripped and not stripped.startswith(("#", ";")):
                k, v = stripped.split("=", 1)
                sections[current_sec][k.strip()] = v.strip()

    return sections


def smart_merge_config(local_conf_path, new_conf_path):
    if not os.path.exists(local_conf_path):
        shutil.copy2(new_conf_path, local_conf_path)
        return

    local_data = parse_conf_sections(local_conf_path)
    used_keys = set()

    with open(new_conf_path, "r", encoding="utf-8", errors="replace") as f:
        new_lines = f.readlines()

    merged_lines = []
    current_sec = "__GLOBAL__"

    def flush_remaining_local_keys(sec_name):
        if sec_name in local_data:
            extra_lines = []
            for k, v in local_data[sec_name].items():
                if (sec_name, k) not in used_keys:
                    extra_lines.append(f"{k} = {v}\n")
                    used_keys.add((sec_name, k))
            if extra_lines:
                insert_pos = len(merged_lines)
                while insert_pos > 0 and merged_lines[insert_pos - 1].strip() == "":
                    insert_pos -= 1
                for idx, line in enumerate(extra_lines):
                    merged_lines.insert(insert_pos + idx, line)

    for raw_line in new_lines:
        stripped = raw_line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            flush_remaining_local_keys(current_sec)
            current_sec = stripped[1:-1].strip()
            merged_lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")
        elif "=" in stripped and not stripped.startswith(("#", ";")):
            k, _ = stripped.split("=", 1)
            k_clean = k.strip()
            if current_sec in local_data and k_clean in local_data[current_sec]:
                merged_lines.append(f"{k_clean} = {local_data[current_sec][k_clean]}\n")
            else:
                merged_lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")
            used_keys.add((current_sec, k_clean))
        else:
            merged_lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")

    flush_remaining_local_keys(current_sec)

    for sec_name, kv_map in local_data.items():
        if sec_name == "__GLOBAL__":
            continue
        unused_in_sec = [(k, v) for k, v in kv_map.items() if (sec_name, k) not in used_keys]
        if unused_in_sec:
            if merged_lines and merged_lines[-1].strip() != "":
                merged_lines.append("\n")
            merged_lines.append(f"[{sec_name}]\n")
            for k, v in unused_in_sec:
                merged_lines.append(f"{k} = {v}\n")
                used_keys.add((sec_name, k))

    with open(local_conf_path, "w", encoding="utf-8") as f:
        f.writelines(merged_lines)


def safe_extract_zip(zip_path, extract_to):
    with zipfile.ZipFile(zip_path, "r") as zf:
        corrupt_file = zf.testzip()
        if corrupt_file is not None:
            raise zipfile.BadZipFile(f"Berkas korup terdeteksi di dalam arsip: {corrupt_file}")

        abs_target = os.path.abspath(extract_to)
        for member in zf.infolist():
            target_path = os.path.abspath(os.path.join(extract_to, member.filename))
            if os.path.commonpath([abs_target, target_path]) != abs_target:
                raise RuntimeError(f"Zip-Slip path traversal terdeteksi: {member.filename}")
            zf.extract(member, extract_to)


def locate_staging_content(staging_dir):
    entries = [e for e in os.listdir(staging_dir) if not e.startswith("__MACOSX")]

    if len(entries) == 1:
        single_path = os.path.join(staging_dir, entries[0])
        if os.path.isdir(single_path):
            if entries[0].lower() == "dapur":
                return single_path, DAPUR_DIR
            sub_entries = [e.lower() for e in os.listdir(single_path)]
            if "dapur" in sub_entries:
                return single_path, PROJECT_ROOT
            return single_path, DAPUR_DIR

    entries_lower = [e.lower() for e in entries]
    if "dapur" in entries_lower:
        return staging_dir, PROJECT_ROOT
    return staging_dir, DAPUR_DIR


def get_target_orchestrator_name(conf):
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".py"):
        return os.path.basename(sys.argv[1])

    cfg_orch = conf.get("orchestrator", "").strip()
    if cfg_orch and os.path.exists(os.path.join(PROJECT_ROOT, cfg_orch)):
        return cfg_orch

    py_candidates = [
        f for f in os.listdir(PROJECT_ROOT)
        if f.lower().endswith(".py") and not f.startswith("__")
    ]
    if py_candidates:
        return py_candidates[0]

    return None


def apply_update(staging_dir, current_conf):
    src_root, target_base = locate_staging_content(staging_dir)
    target_orch_name = get_target_orchestrator_name(current_conf)
    orch_local_path = os.path.join(PROJECT_ROOT, target_orch_name) if target_orch_name else None
    orch_hash_before = calculate_sha256(orch_local_path)

    possible_confs = [
        os.path.join(src_root, "Dapur", "OTA", "ota.conf"),
        os.path.join(src_root, "OTA", "ota.conf"),
        os.path.join(src_root, "ota.conf"),
    ]
    for cand in possible_confs:
        if os.path.exists(cand) and os.path.isfile(cand):
            shutil.copy2(cand, OTA_CONF_PATH)
            current_conf = load_ota_conf(OTA_CONF_PATH)
            logger.info("Aturan manifest ota.conf diperbarui dari paket rilis baru.")
            break

    protect_set = {f.lower().replace("\\", "/") for f in current_conf["protect_files"]}
    backup_set = {f.lower().replace("\\", "/") for f in current_conf["backup_files"]}
    delete_list = current_conf["delete_files"]
    merge_set = {f.lower().replace("\\", "/") for f in current_conf["merge_confs"]}

    for root, _, files in os.walk(src_root):
        rel_dir = os.path.relpath(root, src_root)
        dst_dir = target_base if rel_dir == "." else os.path.join(target_base, rel_dir)
        os.makedirs(dst_dir, exist_ok=True)

        for fname in files:
            src_file = os.path.join(root, fname)
            dst_file = os.path.join(dst_dir, fname)

            rel_to_project = os.path.relpath(dst_file, PROJECT_ROOT).replace("\\", "/")
            rel_to_dapur = (
                os.path.relpath(dst_file, DAPUR_DIR).replace("\\", "/")
                if os.path.commonpath([DAPUR_DIR, os.path.abspath(dst_file)]) == DAPUR_DIR
                else ""
            )

            fname_lower = fname.lower()
            rel_proj_lower = rel_to_project.lower()
            rel_dapur_lower = rel_to_dapur.lower()

            if rel_proj_lower in ("dapur/ota/main.zip", "dapur/ota/ota.log"):
                continue

            identifiers = {fname_lower, rel_proj_lower, rel_dapur_lower}

            if (identifiers & protect_set) and os.path.exists(dst_file):
                logger.info(f"[PROTECT] Tidak menyentuh berkas lokal terproteksi: {rel_to_project}")
                continue

            if identifiers & merge_set:
                if os.path.exists(dst_file):
                    smart_merge_config(dst_file, src_file)
                    logger.info(f"[MERGE_CONF] Menggabungkan konfigurasi: {rel_to_project}")
                else:
                    shutil.copy2(src_file, dst_file)
                    logger.info(f"[MERGE_CONF] Menyalin konfigurasi baru: {rel_to_project}")
                continue

            if (identifiers & backup_set) and os.path.exists(dst_file):
                bak_path = dst_file + ".bak"
                shutil.copy2(dst_file, bak_path)
                logger.info(f"[BACKUP] Mencadangkan berkas lama ke: {rel_to_project}.bak")

            shutil.copy2(src_file, dst_file)
            logger.info(f"[UPDATE] Berkas diperbarui: {rel_to_project}")

    for del_item in delete_list:
        targets = [
            os.path.abspath(os.path.join(DAPUR_DIR, del_item)),
            os.path.abspath(os.path.join(PROJECT_ROOT, del_item)),
        ]
        for target in targets:
            if (
                os.path.commonpath([PROJECT_ROOT, target]) == PROJECT_ROOT
                and os.path.exists(target)
                and os.path.isfile(target)
            ):
                os.remove(target)
                rel_deleted = os.path.relpath(target, PROJECT_ROOT).replace("\\", "/")
                logger.info(f"[DELETE] Berkas usang dihapus: {rel_deleted}")

    orch_hash_after = calculate_sha256(orch_local_path)
    orchestrator_changed = (
        orch_hash_before is not None
        and orch_hash_after is not None
        and orch_hash_before != orch_hash_after
    )

    return current_conf, orchestrator_changed, target_orch_name


def run_ota():
    if os.environ.get("OTA_ALREADY_CHECKED") == "1":
        os.environ.pop("OTA_ALREADY_CHECKED", None)
        logger.info("Sesi baru hasil restart Orchestrator terdeteksi. Melanjutkan proses normal.")
        return

    conf = load_ota_conf(OTA_CONF_PATH)
    zip_url = conf["zip_url"]
    hash_url = conf["hash_url"]
    timeout = conf["timeout"]

    spinner = CLISpinner("Memeriksa status sistem & pembaruan (OTA)")
    spinner.start()

    handle_pip_operations(conf, is_ota_update_triggered=False, spinner=spinner)

    if not zip_url:
        spinner.stop("[i] URL repositori OTA belum dikonfigurasi. Melanjutkan ke modul berikutnya.")
        return

    temp_dir = tempfile.mkdtemp(prefix="ota_sync_")
    temp_zip = os.path.join(temp_dir, "release_incoming.zip")
    orchestrator_changed = False
    target_orchestrator = "Perbarui Data AR.py"

    try:
        local_hash = calculate_sha256(LOCAL_ZIP_PATH)

        if hash_url:
            try:
                remote_hash = fetch_remote_hash(hash_url, timeout=timeout)
                if remote_hash and local_hash and remote_hash == local_hash:
                    spinner.stop("[✓] Sistem sudah versi terbaru (Hash identik).")
                    logger.info(f"Sistem mutakhir. Hash lokal & remote sama ({local_hash[:12]}).")
                    return
            except Exception as h_err:
                logger.warning(f"Gagal memeriksa hash_url ({h_err}). Melanjutkan ke unduhan zip.")

        spinner.update_message("Mengunduh paket pembaruan dari GitHub")
        download_file_with_timeout(zip_url, temp_zip, timeout=timeout)
        new_hash = calculate_sha256(temp_zip)

        if local_hash and new_hash == local_hash:
            spinner.stop("[✓] Sistem sudah menggunakan versi terbaru.")
            logger.info(f"Sistem mutakhir. Hash main.zip cocok ({new_hash[:12]}).")
            return

        spinner.update_message("Mengekstrak dan menerapkan pembaruan sistem")
        logger.info(f"Pembaruan baru ditemukan! Hash lama: {local_hash or 'BARU'} -> Baru: {new_hash}")

        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        safe_extract_zip(temp_zip, extract_dir)

        conf, orchestrator_changed, target_orchestrator = apply_update(extract_dir, conf)

        handle_pip_operations(conf, is_ota_update_triggered=True, spinner=spinner)

        shutil.copy2(temp_zip, LOCAL_ZIP_PATH)
        logger.info(f"Pembaruan sukses. Dapur/OTA/main.zip disimpan (SHA256: {new_hash}).")

        spinner.stop("[✓] Pembaruan sistem OTA berhasil diterapkan!")

    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as net_err:
        spinner.stop("[!] Server GitHub melewati batas waktu (>20s). Melanjutkan versi saat ini.")
        logger.warning(f"Pembaruan OTA dilewati karena kendala jaringan/timeout: {net_err}")
        return
    except Exception as exc:
        spinner.stop(f"[!] Gagal memperbarui sistem ({exc}). Melanjutkan versi lokal.")
        logger.error(f"Kesalahan pada proses OTA: {exc}", exc_info=True)
        return
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if orchestrator_changed and target_orchestrator:
        orch_path = os.path.join(PROJECT_ROOT, target_orchestrator)
        if os.path.exists(orch_path):
            logger.info(f"Orchestrator '{target_orchestrator}' berubah. Memulai ulang proses...")
            print(f"--> [*] Orchestrator diperbarui. Memulai ulang {target_orchestrator}...\n")
            env = os.environ.copy()
            env["OTA_ALREADY_CHECKED"] = "1"
            subprocess.Popen([sys.executable, orch_path], cwd=PROJECT_ROOT, env=env)
            sys.exit(42)


if __name__ == "__main__":
    run_ota()