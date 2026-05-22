import argparse
import asyncio
import json
from datetime import datetime, timezone

from asyncua import Client


def json_default(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def read_nodes(endpoint, node_ids, timeout):
    results = []
    client = Client(endpoint, timeout=timeout)
    async with client:
        namespace_array = await client.get_namespace_array()
        for node_id in node_ids:
            item = {
                "node_id": node_id,
                "ok": False,
            }
            try:
                node = client.get_node(node_id)
                value = await node.read_value()
                item.update(
                    {
                        "ok": True,
                        "value": value,
                        "value_type": type(value).__name__,
                    }
                )
            except Exception as exc:
                item["error"] = repr(exc)
            results.append(item)

    return {
        "command": "VerifyOpcUa",
        "ok": all(item["ok"] for item in results),
        "endpoint": endpoint,
        "namespace_array": namespace_array,
        "read_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Read B&R OPC UA nodes.")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--node", action="append", dest="nodes", default=[])
    parser.add_argument("--nodes-json", help="JSON array of node ids")
    parser.add_argument("--nodes-file", help="Path to a JSON array of node ids")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    node_ids = list(args.nodes)
    if args.nodes_json:
        node_ids.extend(json.loads(args.nodes_json))
    if args.nodes_file:
        with open(args.nodes_file, "r", encoding="utf-8-sig") as handle:
            node_ids.extend(json.load(handle))
    if not node_ids:
        raise SystemExit("At least one --node or --nodes-json value is required.")

    report = asyncio.run(read_nodes(args.endpoint, node_ids, args.timeout))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=json_default))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
