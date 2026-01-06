#!/usr/bin/env python3
"""metrics.py - Compute election metrics from simulation logs."""

import json
import sys
import argparse
from pathlib import Path

def load_states_and_metadata(path):
    """Load state log and extract metadata."""
    states = []
    metadata = {}
    with open(path) as f:
        for line in f:
            data = json.loads(line)
            if "metadata" in data:
                metadata = data
            else:
                states.append(data)
    return states, metadata


def load_config(config_path):
    """Load config file to extract parameters."""
    try:
        with open(config_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def compute_metrics(states):
    results = {
        "total_ticks": len(states),
        "elections_started": 0,
        "agreement_ticks": 0,
        "convergence_times": [],
        "leader_failures": 0,
    }

    prev_leader = None
    leader_lost_tick = None
    prev_elections = set()
    leader_was_offline = False  # Track if leader actually went offline

    for state in states:
        tick = state["tick"]
        nodes = state["nodes"]

        online_nodes = [n for n in nodes if n["online"]]

        if not online_nodes:
            continue

        # --- Metric 1: Convergence Time ---
        # Track when leader goes offline or nodes disagree about leader
        leader_views = {n["leader"] for n in online_nodes}
        all_agree = len(leader_views) == 1
        agreed_leader = next(iter(leader_views)) if all_agree else None

        # Check if current leader is online
        current_leader_online = agreed_leader is not None and any(
            n["uid"] == agreed_leader and n["online"] for n in nodes
        )

        if prev_leader is not None:
            # Check if previous leader went offline
            prev_leader_online = any(n["uid"] == prev_leader and n["online"] for n in nodes)
            if not prev_leader_online and leader_lost_tick is None:
                leader_lost_tick = tick
                leader_was_offline = True
                results["leader_failures"] += 1

        # Also start tracking if nodes disagree (even if leader is still online)
        if not all_agree and leader_lost_tick is None:
            leader_lost_tick = tick

        # Record convergence when:
        # 1. We had a disruption (leader_lost_tick is set)
        # 2. All online nodes now agree
        # 3. The agreed leader is back online (if it was the one that failed)
        if leader_lost_tick is not None and all_agree and current_leader_online:
            convergence_time = tick - leader_lost_tick
            # Record the convergence time (including 0 for instant recovery)
            results["convergence_times"].append(convergence_time)
            prev_leader = agreed_leader
            leader_lost_tick = None
            leader_was_offline = False
        elif all_agree and leader_lost_tick is None:
            prev_leader = agreed_leader

        # --- Metric 2: Election Rate ---
        current_elections = {n["uid"] for n in nodes if n["election"]}
        new_elections = current_elections - prev_elections
        results["elections_started"] += len(new_elections)
        prev_elections = current_elections

        # --- Metric 3: Agreement Ratio ---
        if all_agree:
            results["agreement_ticks"] += 1

    # Compute final metrics
    results["election_rate_per_100"] = (results["elections_started"] / results["total_ticks"]) * 100
    results["agreement_ratio"] = results["agreement_ticks"] / results["total_ticks"]
    results["avg_convergence_time"] = (
        sum(results["convergence_times"]) / len(results["convergence_times"])
        if results["convergence_times"] else 0
    )

    return results

def print_report(results):
    print("=" * 50)
    print("SIMULATION METRICS")
    print("=" * 50)
    print(f"Total ticks:           {results['total_ticks']}")
    print(f"Elections started:     {results['elections_started']}")
    print(f"Election rate:         {results['election_rate_per_100']:.2f} per 100 ticks")
    print(f"Leader failures:       {results['leader_failures']}")
    print("-" * 50)
    print(f"Agreement ratio:       {results['agreement_ratio']*100:.1f}%")
    print(f"Avg convergence time:  {results['avg_convergence_time']:.2f} ticks")
    print(f"Convergence samples:   {len(results['convergence_times'])}")
    print("=" * 50)

def add_parameters(results, metadata=None, config=None, params=None):
    """Add simulation parameters to results for easier plotting."""
    # Priority: explicit params > config file > metadata

    # From metadata (state_log.jsonl first line)
    if metadata:
        if "num_nodes" in metadata:
            results["num_nodes"] = metadata["num_nodes"]
        if "num_ticks" in metadata:
            results["num_ticks"] = metadata["num_ticks"]
        if "seed" in metadata:
            results["seed"] = metadata["seed"]

    # From config file
    if config:
        if "simulation" in config:
            if "num_ticks" in config["simulation"]:
                results["num_ticks"] = config["simulation"]["num_ticks"]
            if "seed" in config["simulation"]:
                results["seed"] = config["simulation"]["seed"]

        if "node" in config:
            if "election_timeout_ticks" in config["node"]:
                results["election_timeout"] = config["node"]["election_timeout_ticks"]
            if "hb_timeout_ticks" in config["node"]:
                results["hb_timeout"] = config["node"]["hb_timeout_ticks"]
            if "p_drop" in config["node"]:
                results["p_drop"] = config["node"]["p_drop"]

        if "failure" in config:
            if "p_fail" in config["failure"]:
                results["p_fail"] = config["failure"]["p_fail"]
            if "leader_fail_multiplier" in config["failure"]:
                results["leader_fail_multiplier"] = config["failure"]["leader_fail_multiplier"]
        # Backwards compatibility: failure params in node section
        elif "node" in config:
            if "p_fail" in config["node"]:
                results["p_fail"] = config["node"]["p_fail"]

    # From explicit params (override everything)
    if params:
        results.update(params)

    return results


def save_results(results, output_path):
    """Save results to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute election metrics from simulation logs")
    parser.add_argument("state_log", nargs="?", default="state_log.jsonl",
                        help="Path to state log file")
    parser.add_argument("-m", "--message-log", help="Path to message log (unused, for compatibility)")
    parser.add_argument("-c", "--config", help="Path to config file to extract parameters")
    parser.add_argument("-s", "--save", help="Save results to JSON file")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress output")

    # Explicit parameter overrides for batch runs
    parser.add_argument("--nodes", type=int, help="Number of nodes")
    parser.add_argument("--p-fail", type=float, help="Failure probability")
    parser.add_argument("--p-drop", type=float, help="Drop probability")
    parser.add_argument("--timeout", type=int, help="Election timeout")

    args = parser.parse_args()

    states, metadata = load_states_and_metadata(args.state_log)
    results = compute_metrics(states)

    # Load config if provided
    config = load_config(args.config) if args.config else None

    # Build explicit params from command line
    explicit_params = {}
    if args.nodes is not None:
        explicit_params["num_nodes"] = args.nodes
    if args.p_fail is not None:
        explicit_params["p_fail"] = args.p_fail
    if args.p_drop is not None:
        explicit_params["p_drop"] = args.p_drop
    if args.timeout is not None:
        explicit_params["election_timeout"] = args.timeout

    # Add parameters to results
    add_parameters(results, metadata, config, explicit_params if explicit_params else None)

    if not args.quiet:
        print_report(results)

    if args.save:
        save_results(results, args.save)
