"""One command on macOS, Linux and Windows: venv -> deps -> data -> build -> dashboard.

    python run.py                    (or ./run.sh, or run.bat)
    python run.py --server.port 8600 (extra args go to `streamlit run`)

Uses only the standard library, so it runs before anything is installed.
Set RVR_DATA=/path/to/data to reuse a local copy of the Big Data Bowl data folder.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
DATA = ROOT / "data"
DATA_REPO = "https://github.com/ThompsonJamesBliss/nfl-big-data-bowl-regional-event-data"
DATA_ZIP = "https://codeload.github.com/ThompsonJamesBliss/nfl-big-data-bowl-regional-event-data/zip/refs/heads/main"


def say(msg):
    print(f"[run] {msg}", flush=True)


def venv_python():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv():
    py = venv_python()
    if not py.exists():
        say("creating .venv ...")
        venv.EnvBuilder(with_pip=True, clear=VENV.exists()).create(VENV)
    if subprocess.run([py, "-m", "pip", "--version"], capture_output=True).returncode != 0:
        say("adding pip to .venv ...")
        subprocess.run([py, "-m", "ensurepip", "--upgrade"], check=True, capture_output=True)
    return py


def ensure_deps(py):
    req = ROOT / "requirements.txt"
    stamp = VENV / ".requirements.sha1"
    h = hashlib.sha1(req.read_bytes()).hexdigest()
    if stamp.exists() and stamp.read_text() == h:
        return
    say("installing requirements (first run only) ...")
    subprocess.run([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", req], check=True)
    stamp.write_text(h)


def has_data(p):
    return (Path(p) / "plays.csv").is_file() and (Path(p) / "tracking").is_dir()


def ensure_data(env):
    ext = os.environ.get("RVR_DATA")
    if ext and has_data(ext):
        say(f"using data from RVR_DATA={ext}")
        return
    if has_data(DATA):
        env.pop("RVR_DATA", None)
        return
    if DATA.is_symlink() or (DATA.exists() and not any(DATA.iterdir())):   # dangling link / empty folder
        DATA.unlink() if DATA.is_symlink() else DATA.rmdir()
    if DATA.exists():
        sys.exit(f"[run] {DATA} exists but has no plays.csv + tracking/. Fix or remove it, then rerun.")
    say("data/ not found: downloading the Big Data Bowl regional data (~830 MB, one time) ...")
    tmp = ROOT / ".bdb_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    if shutil.which("git"):
        try:
            subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", DATA_REPO, str(tmp)],
                           check=True)
            subprocess.run(["git", "-C", str(tmp), "sparse-checkout", "set", "data"], check=True)
            shutil.move(str(tmp / "data"), str(DATA))
            shutil.rmtree(tmp, ignore_errors=True)
            return
        except (subprocess.CalledProcessError, OSError) as e:
            say(f"git download failed ({e}); falling back to the zip archive ...")
            shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    zpath = tmp / "bdb.zip"
    with urllib.request.urlopen(DATA_ZIP) as r, open(zpath, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    with zipfile.ZipFile(zpath) as z:
        members = [m for m in z.namelist() if "/data/" in m]
        z.extractall(tmp, members)
    src = next(tmp.glob("*/data"))
    shutil.move(str(src), str(DATA))
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    if sys.version_info < (3, 10):
        sys.exit(f"[run] Python 3.10+ needed, this is {sys.version.split()[0]}. Install a newer Python and rerun.")
    os.chdir(ROOT)
    env = dict(os.environ)
    py = ensure_venv()
    ensure_deps(py)
    ensure_data(env)
    if not (ROOT / "outputs" / "race_by_play.parquet").exists():
        say("building outputs (all 8 weeks, ~1 min) ...")
        subprocess.run([py, "build.py"], check=True, env=env)
    say("starting the dashboard: open the Local URL printed below (Ctrl+C to stop)")
    try:
        subprocess.run([py, "-m", "streamlit", "run", "app.py", *sys.argv[1:]], env=env)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
