"""PVI trial watchdog: detect Pvi6Man uptime and restart if > 2h.

B&R PVI trial licenses expire after ~2 hours of continuous runtime; after
that every PVI/PVITransfer operation fails with connection errors. This
script checks the Pvi6Man.exe process age and automatically restarts it
when the 2-hour limit is exceeded (or when the process is not running).

Usage:
    python pvi_watchdog.py            # check and restart if needed
    python pvi_watchdog.py --check    # only report, never restart

Exit codes: 0 = healthy/restarted, 2 = check-only & needs restart.
"""
from __future__ import annotations

import subprocess
import sys
import time

MANAGER_EXE = r"C:\Program Files (x86)\BRAutomation\PVI6\Bin\Pvi6Man.exe"
WORKING_DIR = r"C:\Program Files (x86)\BRAutomation\PVI6\Bin"
LIMIT_SECONDS = 2 * 3600

PS_QUERY = (
    "$p = Get-Process -Name 'Pvi6Man' -ErrorAction SilentlyContinue | "
    "Select-Object -First 1; "
    "if ($p) { $age = (Get-Date) - $p.StartTime; "
    "Write-Output ('PID={0} START={1:yyyy-MM-dd HH:mm:ss} AGE_SEC={2:F0}' -f "
    "$p.Id, $p.StartTime, $age.TotalSeconds) } "
    "else { Write-Output 'NOT_RUNNING' }"
)


def run_ps(script: str, timeout: int = 30) -> str:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (proc.stdout or "").strip()


def query_state() -> tuple[str, float]:
    """Return (state, age_seconds). state in {'running','not_running'}."""
    out = run_ps(PS_QUERY)
    if "NOT_RUNNING" in out:
        return "not_running", -1.0
    for line in out.splitlines():
        if line.startswith("PID="):
            parts = dict(
                item.split("=", 1)
                for item in line.split()
                if "=" in item
            )
            age = float(parts.get("AGE_SEC", "-1").replace(",", ""))
            return "running", age
    return "unknown", -1.0


def restart() -> bool:
    stop = (
        "$p = Get-Process -Name 'Pvi6Man' -ErrorAction SilentlyContinue | "
        "Select-Object -First 1; "
        "if ($p) { Stop-Process -Id $p.Id -Force; Start-Sleep -Seconds 3 }"
    )
    run_ps(stop)
    start = (
        f"Start-Process -FilePath '{MANAGER_EXE}' "
        f"-WorkingDirectory '{WORKING_DIR}'; Start-Sleep -Seconds 4"
    )
    run_ps(start)
    state, age = query_state()
    if state == "running":
        print(f"Pvi6Man restarted OK (age now {age:.0f}s)")
        return True
    print(f"RESTART FAILED: state={state}")
    return False


def main() -> int:
    check_only = "--check" in sys.argv
    state, age = query_state()
    print(f"Pvi6Man state={state} age={age:.0f}s" if age >= 0 else f"Pvi6Man state={state}")

    if state == "not_running":
        print("Pvi6Man not running.")
        if check_only:
            print("check-only: would restart.")
            return 2
        print("Starting Pvi6Man ...")
        return 0 if restart() else 1

    if state != "running":
        print("Cannot determine Pvi6Man state; manual check required.")
        return 1

    if age < LIMIT_SECONDS:
        remaining = LIMIT_SECONDS - age
        print(f"OK: within trial window ({remaining/60:.0f} min remaining)")
        return 0

    print(f"EXPIRED: running {age/3600:.1f}h > 2h trial limit.")
    if check_only:
        print("check-only: would restart.")
        return 2
    print("Restarting Pvi6Man ...")
    ok = restart()
    if not ok:
        return 1
    # verify Pvi.py can connect after restart
    time.sleep(2)
    probe = (
        "import time\n"
        "from pvi import Connection, Cpu, Device, Line\n"
        "conn = Connection(timeout=5)\n"
        "flags = {}\n"
        "conn.connectionChanged = lambda c: flags.__setitem__('manager', c)\n"
        "line = Line(conn.root, 'LNANSL', CD='LNANSL')\n"
        "device = Device(line, 'TCP', CD='/IF=TcpIp')\n"
        "cpu = Cpu(device, 'ARSIM', CD='/IP=127.0.0.1 /COMT=2500 /PT=11169')\n"
        "cpu.errorChanged = lambda e: flags.__setitem__('cpu_err', e)\n"
        "deadline = time.time() + 8\n"
        "while time.time() < deadline:\n"
        "    conn.doEvents(); time.sleep(0.05)\n"
        "print('flags:', flags)\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=30
    )
    print(r.stdout.strip() or r.stderr.strip()[-400:])
    if "cpu_err" in r.stdout and "'cpu_err': 0" in r.stdout:
        print("PVI connection verified after restart.")
        return 0
    print("WARNING: PVI connection not verified after restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
