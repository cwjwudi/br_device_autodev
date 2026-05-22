# PLC MCP Server Local Notes

Run from the repository root:

```powershell
python tools\mcp_server\server.py
```

This server exposes the first M2 tools:

- `plc_probe_target`
- `plc_read_pvi`
- `plc_check_download`

The server is a thin JSON-RPC stdio MCP wrapper. It does not implement PLC logic itself; all real work is delegated to:

```powershell
tools\plc_toolchain.ps1
```

Default target is `arsim`. The server runs all commands with the repository root as the working directory.
