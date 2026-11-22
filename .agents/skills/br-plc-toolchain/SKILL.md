---
name: br-plc-toolchain
description: Use the B&R PLC MCP tools and public PviClient Python SDK to build, run, trace, and verify an Automation Studio project on ARsim or an explicitly authorized PLC.
---

# B&R PLC development

## 1. Project & Deployment Baseline

- Read the project `br-auto-dev.json`; do not guess the project, target, toolchain, IP, or test values.
- Use `plc_validate_environment` and `plc_doctor`, then `plc_build_project` with `build_ruc_package=true`.
- For a fresh ARsim, check `plc_check_arsim_occupancy`, then call `plc_provision_arsim` with the explicit target and `execute=true`. It installs the RUC to a new subdirectory of `arsim_work_dir` or `<project>/Temp/Simulation`.
- AS4 uses the project's `SimulationIPAddress` (default `127.0.0.1`); if it differs from the target, fix the simulation configuration and rebuild before provisioning.
- An occupied IP is not a reservation and must not be taken over. Inspect ownership; do not stop another project.
- Provisioning confirms an owned listener, not RUN or application correctness. Use `plc_discover_runtime_target` and `plc_read_runtime_variable` / `plc_read_pvi_batch` or task-specific log checks to verify feedback.
- To update an existing target, use `plc_check_download` and review identity and warnings, then `plc_download_ruc` with explicit authorization and `execute=true`. Never bypass a failed safety check.
- Bound waits and retries. After a timeout or unknown transfer result, inspect target state and logs before attempting another change.

## 2. Layered Tool & SDK Selection

Choose the lightest interface that fits the task:

1. **Simple single-point query or control**:
   - Use MCP tools `plc_read_runtime_variable` / `plc_write_runtime_variable` directly (plus `plc_runtime_health` and `plc_get_runtime_variable_info` when checking connection health, data type, or writability).
2. **Synchronous multi-object snapshot (up to 128 variables)**:
   - Call MCP `plc_read_pvi_batch` directly. Do **not** loop `plc_read_runtime_variable` one by one.
3. **State-machine stalls & transient timing capture (down to 20 ms, up to 128 variables)**:
   - Call MCP `plc_start_pvi_trace` (minimum `interval_ms=20`, up to `128` variables) -> trigger state change via write -> monitor with `plc_get_pvi_trace_status` -> finish with `plc_stop_pvi_trace` / `plc_read_pvi_trace`.
   - For post-mortem analysis of large `var/traces/*.jsonl` files (state transition timelines, dropped-sample intervals, anomaly aggregation), write a read-only Python analysis script against the `trace_file` path.
4. **Multi-step closed-loop orchestration & automated regression (standalone Python SDK)**:
   - When a workflow requires *"write command -> condition wait -> staged high-density tracing -> comparison / transition analysis"* across many steps, write an autonomous Python script using the public SDK (`from br_plc_toolchain import PviClient`) executed via `br_device_autodev/.venv/Scripts/python.exe` (with `PYTHONPATH=src` if needed) so one process session reuses a persistent PVI connection.
   - Minimal standard template:

     ```python
     from br_plc_toolchain import PviClient

     with PviClient.from_project(r"C:\path\to\project", target="arsim") as plc:
         plc.discover()
         trace = plc.start_trace(["Main:eState", "gAlive"], duration_seconds=10, interval_ms=20)
         plc.write("Main:bStart", True, execute=True)
         plc.wait_until("Main:eState", lambda v: v == 3, timeout_s=5.0, interval_s=0.05)
         summary = plc.stop_trace(trace["trace_id"])
         data = plc.read_trace(trace["trace_id"], max_samples=1000)
         print(summary["trace_file"], summary["actual_interval_ms"], summary["dropped_samples"])
     ```

   - For >128 variables, use `plc.read_chunked(variables)` or `plc.read_many(variables, chunked=True)`.
   - For multi-variable writes, use `plc.write_many(writes, execute=True)` so every item passes `RuntimePolicy` and readback verification.

## 3. Prohibitions, Process Isolation & Safety Rules

- **NEVER** import, inspect, or reflect private objects from `tools.mcp_server.toolchain` (such as `TOOLS`, `_RUNTIME_SERVICE`, or `_TRACE_MANAGER`). Always use `from br_plc_toolchain import PviClient` or MCP tools.
- **Process isolation**: A standalone Python script creates and owns its own persistent PVI worker and closes it automatically when exiting the `with PviClient...:` block. It does **not** share in-memory handles with the MCP Server process. Prefer MCP tools for short, interactive queries, and reserve standalone `PviClient` scripts for multi-step closed-loop orchestration and automated regression tests.
- **Safety & authorization**:
  - Script writes are strictly restricted to local ARsim or explicitly authorized test targets.
  - Strictly obey `br-auto-dev.json` (`role`, `write_policy`, `write_blacklist` / `write_whitelist`) and project `AGENTS.md` prohibitions against modifying or writing Safety objects or physical I/O.
  - `production` targets permanently reject writes.
- Fix reported errors, rebuild, redeploy, and recheck until the user's observable acceptance criteria pass or a concrete blocker remains.
- Report build, deployment, PVI/runtime, and application results separately, including logs and limitations. Never infer physical PLC authorization from ARsim permission.
