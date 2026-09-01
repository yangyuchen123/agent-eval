"""Inventory real AgentOctagon attempts for MetaEval case selection."""
from __future__ import annotations
import argparse, json
from agenteval.meta_eval import OctagonDiscovery, write_inventory

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/yang/agent-octagon")
    parser.add_argument("--env")
    parser.add_argument("--task")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", default="run/meta_eval/octagon-inventory/inventory.json")
    args = parser.parse_args()
    discovery = OctagonDiscovery(args.root)
    attempts = discovery.discover(env_name=args.env, task_id=args.task, limit=args.limit)
    write_inventory(args.output, attempts, discovery.environment_inventory())
    groups = discovery.task_groups(attempts)
    summary = {"attempt_count": len(attempts), "environment_count": len(discovery.environment_inventory()), "repeat_groups": {key: len(value) for key, value in groups.items() if len(value) > 1}}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
