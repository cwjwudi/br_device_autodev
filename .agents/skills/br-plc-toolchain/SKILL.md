---
name: br-plc-toolchain
description: Use the B&R PLC MCP tools to build, run, and verify an Automation Studio project on ARsim or an explicitly authorized PLC.
---

# B&R PLC development

- Read the project `br-auto-dev.json`; do not guess the project, target, toolchain, IP, or test values.
- Use `plc_validate_environment` and `plc_doctor`, then `plc_build_project` with `build_ruc_package=true`.
- For a fresh ARsim, check `plc_check_arsim_occupancy`, then call `plc_provision_arsim` with the explicit target and `execute=true`. It installs the RUC to a new subdirectory of `arsim_work_dir` or `<project>/Temp/Simulation`.
- AS4 uses the project's `SimulationIPAddress` (default `127.0.0.1`); if it differs from the target, fix the simulation configuration and rebuild before provisioning.
- An occupied IP is not a reservation and must not be taken over. Inspect ownership; do not stop another project.
- Provisioning confirms an owned listener, not RUN or application correctness. Use `plc_discover_runtime_target` and `plc_read_runtime_variable` or task-specific log checks to verify feedback.
- To update an existing target, use `plc_check_download` and review identity and warnings, then `plc_download_ruc` with explicit authorization and `execute=true`. Never bypass a failed safety check.
- Bound waits and retries. After a timeout or unknown transfer result, inspect target state and logs before attempting another change.
- Fix reported errors, rebuild, redeploy, and recheck until the user's observable acceptance criteria pass or a concrete blocker remains.
- Report build, deployment, PVI/runtime, and application results separately, including logs and limitations. Never infer physical PLC authorization from ARsim permission.
