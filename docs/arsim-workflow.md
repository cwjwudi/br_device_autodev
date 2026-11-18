# ARsim workflow

Configure an ARsim target and IP in `br-auto-dev.json`. `arsim_work_dir` is optional; relative paths are resolved against that JSON file. If omitted, the work root is the `.apj` directory's `Temp/Simulation`. The legacy `arsim_loader_exe` remains supported by `plc_start_arsim` for an existing runtime.

Build with `plc_build_project(build_ruc_package=true)`. `plc_check_arsim_occupancy` reports TCP listeners on ports 80, 81, 4840 and 11169 for the selected loopback addresses; an empty sample is not a reservation and does not detect unlisted ports. `plc_provision_arsim(target=..., execute=true)` samples again under the toolchain's allocation lock, checks the RUC is an ARsim package, installs into a fresh `codex-arsim/<run-id>/runtime` directory, starts it and verifies the PVI listener belongs to that directory. It never overwrites an existing run. An outside process can still race for an address.

AS4 uses `CreateARsimStructure`; AS6 uses `OfflineCommissioning`. AS4's `SimulationIPAddress` in `Physical/<config>/Hardware.hw` must match the target IP (default 127.0.0.1); rebuild after changing it. ARsim process/listener readiness does not establish RUN or application correctness. Use `plc_discover_runtime_target` and `plc_read_runtime_variable` for online feedback, and validate project-specific outputs separately. Provisioning is an initial offline installation; existing-instance online updates use `plc_check_download` and `plc_download_ruc`.

Only ARsim loopback targets with automatic download enabled are accepted for provisioning. Results include the run directory, install log, IP and owned process IDs. Failed startups are cleaned up by process tree, while installed files and logs are retained for diagnosis. Stop only an instance whose identity and ownership have been verified. Runtimes and their data are not automatically deleted.

The project-local [br-plc-toolchain skill](../.agents/skills/br-plc-toolchain/SKILL.md) describes the AI workflow. AS4 and AS6 PVI DLL families require separate server processes; do not switch an already initialized PVI worker between families.
