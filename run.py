import logging
import socket
import subprocess
import sys

import uvicorn

HOST = "127.0.0.1"
PORT = 8770


def _port_owner(port: int):
    """PID and image name of whatever is listening on `port`, if anything.

    Uvicorn's own failure for this is a bare WinError 10048 printed *after*
    the whole app has started up -- including a Whisper model load -- which
    reads like a crash rather than "something else is already running".
    """
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return None, None

    pid = None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[1].endswith(f":{port}") \
                and parts[3].upper() == "LISTENING":
            pid = parts[4]
            break
    if not pid:
        return None, None

    name = None
    try:
        info = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if info.startswith('"'):
            name = info.split('","')[0].strip('"')
    except Exception:
        pass
    return pid, name


def _check_port_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Without SO_EXCLUSIVEADDRUSE Windows can report a port as bindable
        # while another process still holds it, so this must mirror how
        # uvicorn actually binds.
        try:
            s.bind((HOST, PORT))
            return True
        except OSError:
            return False


if __name__ == "__main__":
    # Without this, every log.info/log.warning in the services is silently
    # dropped -- including "ears: heard ..." and the boot sequence, which are
    # the two things you actually want to watch while using the HUD.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%I:%M:%S %p",
    )
    logging.getLogger("jarvis").setLevel(logging.INFO)

    # Checked before uvicorn starts anything: otherwise the port error only
    # surfaces after ~15s of model loading and vault reading, and lands
    # underneath a wall of startup logs where it is easy to miss.
    if not _check_port_free():
        pid, name = _port_owner(PORT)
        print(f"\nJarvis is already running on {HOST}:{PORT}.\n", file=sys.stderr)
        if pid:
            print(f"  Held by PID {pid}" + (f" ({name})" if name else ""), file=sys.stderr)
            print(f"  Stop it with:  taskkill /F /PID {pid}\n", file=sys.stderr)
        else:
            print(f"  Stop it with:  npx kill-port {PORT}\n", file=sys.stderr)
        print("Then run this again.", file=sys.stderr)
        raise SystemExit(1)

    uvicorn.run("jarvis.app:app", host=HOST, port=PORT, reload=False)
