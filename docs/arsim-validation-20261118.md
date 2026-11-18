# ARsim validation — 2026-11-18

On this workstation, the AS4 project `p801_plc_debug_log/as-project/StdLibs.apj` and AS6 project `p102_test_report/test_report/test_report.apj` were built through the current MCP server, commissioned from their RUCs into separate default `Temp/Simulation/codex-arsim` directories, and then updated online through `plc_download_ruc` without a safety bypass. Both were observed RUN simultaneously and queried via separate PVI4/PVI6 MCP server processes.

| Project | Build | IP / runtime | PVI result |
| --- | --- | --- | --- |
| AS4 p801 | 0 errors, existing Pb_lib warning 9255; attempt `3b6fc99faa474d4dbaf43ee8343a2378` | `127.0.0.2`, J4.93, runtime PID 105056 | RUN; `TEST:s=4` |
| AS6 p102 | 0 errors, MpReport warning 9345; attempt `6a08840c32a9425f8a3d3f9c36bbc89f` | `127.0.0.1`, 6.7.8, runtime PID 79960 | RUN; `Program:spacingStatus=1` |

The occupancy MCP tool reported both addresses occupied by the respective runtime and 127.0.0.3 free. A second attempt to provision at 127.0.0.2 was rejected with `ARSIM_IP_OCCUPIED`. Initial offline installation logs remain in the respective run directories. Online transfer logs are `var/downloads/e270902762d249b6b3822bf8a1e49fdb/pvi_download_arsim.log` (AS4) and `var/downloads/a3053b657eeb47fbb2e3ce0c5e4cba7c/pvi_download_arsim.log` (AS6). The tool reported successful transfer logs and subsequent runtime probes; the transfer wrappers did not exit during their grace period and were cleaned up. PVI samples and the occupancy result are in `var/arsim-as4-pvi-20261118.jsonl`, `var/arsim-as6-pvi-20261118.jsonl`, and `var/arsim-occupancy-20261118.json`.

The first AS4 startup showed that J4.93 ignored the AS6 `-simulationIP` override and bound the configured default 127.0.0.1. Its owned processes were stopped; setting `SimulationIPAddress=127.0.0.2` in the AS4 hardware configuration and rebuilding fixed the simultaneous run. Parallel AS4/AS6 builds produced error 9207 because Automation Studio serializes builds; sequential builds passed. Both sample projects had the removed `access_policy` field in local `br-auto-dev.json`; it was removed so the current server could load them. An old AS4 loader setting caused an unrelated `Get-FileHash` failure and could refer to a different runtime; it was removed from that project's local configuration before retesting.

The tools confirm these specific versions and variables only. They do not establish full application acceptance, guarantee that unmonitored ports are conflict-free, or reserve an IP against processes outside the toolchain. Online download checks warn that some target metadata is unavailable; in this test the running instances were independently identified by their owned directories and PIDs. The reported state after transfer is runtime reachable, with RUN independently confirmed through PVI.

Current runtime policy allows writes to writable ARsim variables when `execute=true`, regardless of the PVI write list. The obsolete `access_policy` field does not restore those restrictions in the current server. No PVI variables were written during this test; review this behavior before using the projects with broader automation.
