ota_script = os.path.join(folder_dapur, "00_OTAUpdater.py")
    if os.path.exists(ota_script):
        res = subprocess.run([sys.executable, ota_script, os.path.basename(__file__)])
        if res.returncode == 42:
            sys.exit(0)
