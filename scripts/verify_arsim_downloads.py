"""Exercise live, pre-provisioned loopback ARsim targets with an independent MCP client."""

import argparse
from datetime import datetime, timezone
from ipaddress import ip_address
import itertools
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid


REPO = Path(__file__).resolve().parents[1]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", required=True, nargs=2, metavar=("PROJECT", "TARGET"))
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    sys.path.insert(0, str(REPO / "tools" / "mcp_server"))
    from locks import resolve_scope_context

    cases = []
    for project, target in options.case:
        args = {"project_path": str(Path(project).resolve()), "target": target}
        context = resolve_scope_context(args)
        if context["target_role"] != "arsim" or not ip_address(context["target_ip"]).is_loopback:
            parser.error(f"{target} is not a configured loopback ARsim.")
        cases.append((f"{Path(project).name}:{target}", args))
    env = os.environ.copy()
    env["PSModulePath"] = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/Modules")
    stamp = uuid.uuid4().hex[:12]
    with options.output.open("x", encoding="utf-8", buffering=1) as output, options.output.with_suffix(".stderr.log").open("x", encoding="utf-8") as stderr:
        server = subprocess.Popen(
            [sys.executable, str(REPO / "tools/mcp_server/server.py")], cwd=REPO,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, env=env,
        )
        messages = queue.Queue()

        def read():
            try:
                for line in server.stdout:
                    messages.put((utc_now(), json.loads(line.decode("utf-8"))))
            except (UnicodeError, ValueError) as exc:
                messages.put((utc_now(), {"client_parse_error": str(exc)}))
            finally:
                messages.put((utc_now(), {"client_error": "stdio closed"}))

        threading.Thread(target=read, daemon=True).start()
        ids = itertools.count(1)

        def send(message):
            server.stdin.write((json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False) + "\n").encode("utf-8"))
            server.stdin.flush()

        def rpc(method, params, timeout=65):
            request_id = f"验证-{stamp}-{next(ids)}"
            started = utc_now()
            clock = time.monotonic()
            send({"id": request_id, "method": method, "params": params})
            while True:
                try:
                    received, response = messages.get(timeout=max(0, timeout - (time.monotonic() - clock)))
                except queue.Empty:
                    received, response = None, {"client_error": f"No matching response within {timeout}s"}
                    break
                if response.get("id") == request_id or "client_error" in response or "client_parse_error" in response:
                    break
                output.write(json.dumps({"unmatched_response": response, "received_at": received}) + "\n")
            return {
                "rpc_id": request_id, "sent_at": started, "received_at": received,
                "seconds": round(time.monotonic() - clock, 3), "response": response,
            }

        def call(name, arguments, timeout=65):
            event = rpc("tools/call", {"name": name, "arguments": arguments}, timeout)
            return event, event["response"].get("result", {}).get("structuredContent", {})

        try:
            ready = rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "arsim-download-verifier", "version": "1"}}, 10)
            if "result" not in ready["response"]:
                raise RuntimeError(ready)
            send({"method": "notifications/initialized"})
            completed = 0
            closed_count = 0
            exercised = set()
            quarantined = set()
            for round_index, (case, args) in enumerate(itertools.cycle(cases), start=1):
                if round_index > options.count * 3 or len(quarantined) == len(cases):
                    break
                if case in quarantined:
                    continue
                check, gate = call("plc_check_download", args)
                if not gate.get("ok"):
                    output.write(json.dumps({"case": case, "round": round_index, "safety_check": check}) + "\n")
                    print(f"{case} standalone safety check failed: {gate.get('error_code')}", flush=True)
                    continue
                request_id = f"arsim-{stamp}-{round_index}"
                attempt, result = call("plc_download_ruc", {**args, "execute": True, "request_id": request_id})
                lookup, recovery = call("plc_get_download_result", {"request_id": request_id}, 8)
                data = (recovery.get("result") or {}).get("data", {})
                state = recovery.get("download_state")
                returned = attempt["response"].get("id") == attempt["rpc_id"] and bool(result)
                classified = state in {"not_started", "transfer_succeeded", "transfer_failed", "unknown"}
                closed = (
                    classified and bool(recovery.get("next_action")) and recovery.get("operation_id")
                    and (not returned or result.get("attempt_id") == recovery["operation_id"])
                    and (state == "transfer_succeeded" or bool(result.get("error_code") or data.get("error_code") or recovery.get("error_code")))
                )
                completed += 1
                closed_count += bool(closed)
                exercised.add(case)
                output.write(json.dumps({
                    "case": case, "attempt": completed, "request_id": request_id, "safety_check": check,
                    "download": attempt, "lookup": lookup, "closed": bool(closed),
                }, ensure_ascii=False) + "\n")
                print(f"{completed}/{options.count} {case} {state} {attempt['seconds']}s reply={returned} closed={bool(closed)}", flush=True)
                if not closed or state == "unknown" or recovery.get("target_protected"):
                    quarantined.add(case)
                    print(f"Paused {case}: investigate {request_id} before further downloads.", flush=True)
                if completed >= options.count:
                    return int(closed_count != completed or exercised != {label for label, _ in cases})
            return 1
        finally:
            server.stdin.close()
            try:
                server.wait(timeout=65)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
