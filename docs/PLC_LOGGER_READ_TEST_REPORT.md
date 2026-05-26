# PLC/AR Logger Read Test Report

## Summary

- Generated at UTC: `2026-05-26T02:14:47.228178+00:00`
- Target: `test_plc`
- Target IP: `192.168.50.222`
- Target role: `dedicated_test_plc`
- Logger module: `System / $arlogsys`
- Format: `.html`
- CLI result: `ok=true`
- Process exit code: `0`
- Output path: `tools/.generated/logger/20260526_021319_test_plc_System_arlogsys.html`
- PVITransfer log path: `tools/.generated/logger/20260526_021319_test_plc_System_arlogsys.html.pvitransfer.log`
- PIL path: `tools/.generated/logger/20260526_021319_test_plc_System_arlogsys.html.pil`
- Output size: `17511` bytes

## Verdict

PASS: `ReadLogger` successfully read the whitelisted System logger from `test_plc` and generated an HTML report inside the repository.

## Safety Checks

- Operation type: read-only PVITransfer `Logger` command.
- No PLC variables were written.
- No download was attempted.
- Logger requested is in `logger.allowed_modules`: `System / $arlogsys`.
- Safety logger was not requested.
- Output file stayed inside `tools/.generated/logger/`.
- Target role is `dedicated_test_plc`, not `production`.

## Logger Summary

- Parsed entries: `26`
- Latest timestamp in logger: `2020-04-26T16:33:28.287661`
- Severity counts:
  - `Info`: `17`
  - `Success`: `7`
  - `Warning`: `2`

## PVITransfer Execution Log

```text
PROCESS STARTED: 26-05-2026, 10:13:21
1: @START@ "D:\codex_ws\motion_svg_test\tools\.generated\logger\20260526_021319_test_plc_System_arlogsys.html.pil"
2: Connection "/IF=tcpip", "/IP=192.168.50.222 /COMT=2500 /AM=* /PT=11169", "WT=30"
Connection "/IF=tcpip", "/IP=192.168.50.222 /COMT=2500 /AM=* /PT=11169", "WT=30" SUCCESSFUL
3: Logger "System", "$arlogsys", ".html", "D:\codex_ws\motion_svg_test\tools\.generated\logger\20260526_021319_test_plc_System_arlogsys.html", "en"
Logger "System", "$arlogsys", ".html", "D:\codex_ws\motion_svg_test\tools\.generated\logger\20260526_021319_test_plc_System_arlogsys.html", "en" SUCCESSFUL
4: @END@ "D:\codex_ws\motion_svg_test\tools\.generated\logger\20260526_021319_test_plc_System_arlogsys.html.pil"
PROCESS FINISHED (SUCCESS): 26-05-2026, 10:13:22
```

## Acquired Logger Entries

| # | Severity | Time | ID | RecordID | Entered by | ASCII Data | Detail |
|---:|---|---|---:|---:|---|---|---|
| 1 | Info | 2020-04-26T13:01:41.667000 | 31280 | 1 | ROOT | base log module created | AR logger module created |
| 2 | Info | 2020-04-26T13:01:40.027000 | 9200 | 2 | ROOT | Boot:Powerup | System halted because of power loss |
| 3 | Warning | 2020-04-26T13:01:49.973000 | 30028 | 3 | ROOT | reboot required - modified hardware description (hwd) and/or firmware available | Carried out reboot |
| 4 | Info | 2020-04-26T13:02:00.888000 | 9207 | 4 | ROOT | Boot:Software Reset | PLC reboot triggered by a software reset |
| 5 | Warning | 2020-04-26T13:02:04.787000 | 9227 | 5 | ROOT | Boot | Warning: Warm restart after software reset |
| 6 | Info | 2020-04-26T13:02:13.035000 | 1076900505 | 6 | ROOT |  |  |
| 7 | Info | 2020-04-26T13:02:14.012000 | 1076899103 | 7 | ROOT |  |  |
| 8 | Success | 2020-04-26T13:02:14.012000 | 3157279 | 8 | ROOT |  |  |
| 9 | Info | 2020-04-26T13:12:40.532391 | 1076899102 | 9 | anslAsync_1 |  |  |
| 10 | Info | 2020-04-26T13:12:43.393391 | 1076899103 | 10 | anslAsync_1 |  |  |
| 11 | Success | 2020-04-26T13:12:43.393391 | 3157279 | 11 | anslAsync_1 |  |  |
| 12 | Info | 2020-04-26T13:59:51.982938 | 1076899102 | 12 | anslAsync_1 |  |  |
| 13 | Info | 2020-04-26T13:59:54.856948 | 1076899103 | 13 | anslAsync_1 |  |  |
| 14 | Success | 2020-04-26T13:59:54.856948 | 3157279 | 14 | anslAsync_1 |  |  |
| 15 | Info | 2020-04-26T14:05:54.951871 | 1076899102 | 15 | anslAsync_1 |  |  |
| 16 | Info | 2020-04-26T14:05:57.561792 | 1076899103 | 16 | anslAsync_1 |  |  |
| 17 | Success | 2020-04-26T14:05:57.561792 | 3157279 | 17 | anslAsync_1 |  |  |
| 18 | Info | 2020-04-26T14:08:43.567569 | 1076899102 | 18 | anslAsync_1 |  |  |
| 19 | Info | 2020-04-26T14:08:46.276492 | 1076899103 | 19 | anslAsync_1 |  |  |
| 20 | Success | 2020-04-26T14:08:46.276492 | 3157279 | 20 | anslAsync_1 |  |  |
| 21 | Info | 2020-04-26T15:28:02.657503 | 1076899102 | 21 | anslAsync_1 |  |  |
| 22 | Info | 2020-04-26T15:28:04.814412 | 1076899103 | 22 | anslAsync_1 |  |  |
| 23 | Success | 2020-04-26T15:28:04.814412 | 3157279 | 23 | anslAsync_1 |  |  |
| 24 | Info | 2020-04-26T16:33:26.857643 | 1076899102 | 24 | anslAsync_1 |  |  |
| 25 | Info | 2020-04-26T16:33:28.287661 | 1076899103 | 25 | anslAsync_1 |  |  |
| 26 | Success | 2020-04-26T16:33:28.287661 | 3157279 | 26 | anslAsync_1 |  |  |

## Raw CLI JSON

```json
{
  "command": "ReadLogger",
  "ok": true,
  "target_ip": "192.168.50.222",
  "target_role": "dedicated_test_plc",
  "logger_type": "System",
  "logger_name": "$arlogsys",
  "format": ".html",
  "output_path": "D:\\codex_ws\\motion_svg_test\\tools\\.generated\\logger\\20260526_021319_test_plc_System_arlogsys.html",
  "log_path": "D:\\codex_ws\\motion_svg_test\\tools\\.generated\\logger\\20260526_021319_test_plc_System_arlogsys.html.pvitransfer.log",
  "error_summary": null,
  "pil_path": "D:\\codex_ws\\motion_svg_test\\tools\\.generated\\logger\\20260526_021319_test_plc_System_arlogsys.html.pil",
  "output_exists": true,
  "output_size_bytes": 17511,
  "output_tail": [
    "PROCESS STARTED: 26-05-2026, 10:13:21",
    "1: @START@ \"D:\\codex_ws\\motion_svg_test\\tools\\.generated\\logger\\20260526_021319_test_plc_System_arlogsys.html.pil\"",
    "2: Connection \"/IF=tcpip\", \"/IP=192.168.50.222 /COMT=2500 /AM=* /PT=11169\", \"WT=30\"",
    "Connection \"/IF=tcpip\", \"/IP=192.168.50.222 /COMT=2500 /AM=* /PT=11169\", \"WT=30\" SUCCESSFUL",
    "3: Logger \"System\", \"$arlogsys\", \".html\", \"D:\\codex_ws\\motion_svg_test\\tools\\.generated\\logger\\20260526_021319_test_plc_System_arlogsys.html\", \"en\"",
    "Logger \"System\", \"$arlogsys\", \".html\", \"D:\\codex_ws\\motion_svg_test\\tools\\.generated\\logger\\20260526_021319_test_plc_System_arlogsys.html\", \"en\" SUCCESSFUL",
    "4: @END@ \"D:\\codex_ws\\motion_svg_test\\tools\\.generated\\logger\\20260526_021319_test_plc_System_arlogsys.html.pil\"",
    "PROCESS FINISHED (SUCCESS): 26-05-2026, 10:13:22"
  ],
  "stderr": null,
  "process_exit_code": 0,
  "target": "test_plc"
}
```
