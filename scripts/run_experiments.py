#!/usr/bin/env python3
"""run_experiments.py - Run simulation experiments across parameter space."""

import json
import subprocess
import argparse
from pathlib import Path
from itertools import product
import shutil
import sys

# ============================================================
# Path Resolution
# ============================================================

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent

def find_executable():
    """Find the simulation executable in common locations."""
    candidates = [
        PROJECT_DIR / "build" / "mpi_bully_sim",
        PROJECT_DIR / "cmake-build-debug" / "mpi_bully_sim",
        PROJECT_DIR / "cmake-build-release" / "mpi_bully_sim",
        PROJECT_DIR / "mpi_bully_sim",
    ]

    for path in candidates:
        if path.exists() and path.is_file():
            return str(path)

    return None

def get_metrics_script():
    """Get path to metrics.py script."""
    return SCRIPT_DIR / "metrics.py"

# ============================================================
# Configuration
# ============================================================

# Parameter space
DEFAULT_PARAMS = {
    "nodes": [5, 10, 15, 20],
    "p_fail": [0.02, 0.05, 0.10],
    "p_drop": [0.0, 0.05, 0.10],
    "timeout": [3],  # Keep fixed unless testing timing
}

# Base configuration template
BASE_CONFIG = {
    "simulation": {
        "num_ticks": 1000,
        "seed": 12345
    },
    "node": {
        "hb_period_ticks": 1,
        "hb_timeout_ticks": 3,
        "election_timeout_ticks": 3,
        "p_send": 0.30,
        "p_drop": 0.0,
        "max_recv_per_tick": 64
    },
    "failure": {
        "type": "network",
        "p_fail": 0.02,
        "leader_fail_multiplier": 1.5,
        "offline_durations": [1, 2, 3, 5],
        "offline_weights": [70, 20, 7, 3]
    },
    "logging": {
        "state_log_file": "state_log.jsonl",
        "message_log_file": "message_log.jsonl",
        "debug_log_file": "debug_log.jsonl",
        "verbose": False
    }
}

# ============================================================
# Helpers
# ============================================================

def config_name(nodes, p_fail, p_drop, timeout):
    """Generate config name from parameters."""
    return f"n{nodes}_pf{p_fail}_pd{p_drop}_t{timeout}"

def generate_config(nodes, p_fail, p_drop, timeout, seed=12345):
    """Generate config dict for given parameters."""
    config = json.loads(json.dumps(BASE_CONFIG))  # Deep copy

    config["simulation"]["seed"] = seed
    config["node"]["election_timeout_ticks"] = timeout
    config["node"]["p_drop"] = p_drop
    config["failure"]["p_fail"] = p_fail

    return config

def run_simulation(executable, config_path, num_nodes, mpi_args=None):
    """Run MPI simulation."""
    np = num_nodes + 1  # +1 for controller

    cmd = ["mpirun", "--oversubscribe", "-np", str(np)]

    if mpi_args:
        cmd.extend(mpi_args.split())

    cmd.extend([executable, "-config", str(config_path)])

    result = subprocess.run(cmd, capture_output=True, text=True)

    return result.returncode == 0, result.stdout, result.stderr

def compute_metrics(state_log, message_log, output_json, config_file=None,
                    nodes=None, p_fail=None, p_drop=None, timeout=None):
    """Run metrics.py to compute metrics."""
    metrics_script = get_metrics_script()

    cmd = [
        sys.executable, str(metrics_script),
        str(state_log),
        "-m", str(message_log),
        "-s", str(output_json),
        "-q"  # Quiet mode for batch runs
    ]

    # Add config file for parameter extraction
    if config_file:
        cmd.extend(["-c", str(config_file)])

    # Add explicit parameters
    if nodes is not None:
        cmd.extend(["--nodes", str(nodes)])
    if p_fail is not None:
        cmd.extend(["--p-fail", str(p_fail)])
    if p_drop is not None:
        cmd.extend(["--p-drop", str(p_drop)])
    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

# ============================================================
# Main Experiment Runner
# ============================================================

def run_experiments(
    executable,
    output_dir,
    nodes_list,
    p_fail_list,
    p_drop_list,
    timeout_list,
    num_runs=1,
    seed_base=12345,
    mpi_args=None,
    dry_run=False
):
    """Run all experiments in parameter space."""

    output_path = Path(output_dir)
    configs_path = output_path / "configs"
    logs_path = output_path / "logs"
    results_path = output_path / "results"

    # Create directories
    for p in [output_path, configs_path, logs_path, results_path]:
        p.mkdir(parents=True, exist_ok=True)

    # Generate experiment list
    experiments = list(product(nodes_list, p_fail_list, p_drop_list, timeout_list))
    total = len(experiments) * num_runs

    print(f"=" * 60)
    print(f"EXPERIMENT PLAN")
    print(f"=" * 60)
    print(f"Parameter space:")
    print(f"  nodes:   {nodes_list}")
    print(f"  p_fail:  {p_fail_list}")
    print(f"  p_drop:  {p_drop_list}")
    print(f"  timeout: {timeout_list}")
    print(f"-" * 60)
    print(f"Total configurations: {len(experiments)}")
    print(f"Runs per config:      {num_runs}")
    print(f"Total runs:           {total}")
    print(f"Output directory:     {output_dir}")
    print(f"Executable:           {executable}")
    print(f"=" * 60)

    if dry_run:
        print("\n[DRY RUN] Would run the following experiments:")
        for nodes, p_fail, p_drop, timeout in experiments:
            name = config_name(nodes, p_fail, p_drop, timeout)
            print(f"  - {name}")
        return

    # Run experiments
    completed = 0
    failed = []

    for nodes, p_fail, p_drop, timeout in experiments:
        name = config_name(nodes, p_fail, p_drop, timeout)

        for run_idx in range(num_runs):
            run_name = f"{name}_r{run_idx}" if num_runs > 1 else name
            seed = seed_base + run_idx

            print(f"\n[{completed + 1}/{total}] Running: {run_name}")

            # Generate config
            config = generate_config(nodes, p_fail, p_drop, timeout, seed)
            config_file = configs_path / f"{run_name}.json"

            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)

            # Create run directory
            run_log_dir = logs_path / run_name
            run_log_dir.mkdir(exist_ok=True)

            # Update log paths in config
            config["logging"]["state_log_file"] = str(run_log_dir / "state_log.jsonl")
            config["logging"]["message_log_file"] = str(run_log_dir / "message_log.jsonl")
            config["logging"]["debug_log_file"] = str(run_log_dir / "debug_log.jsonl")

            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)

            # Run simulation
            success, stdout, stderr = run_simulation(executable, config_file, nodes, mpi_args)

            if not success:
                print(f"  ✗ Simulation failed")
                if stderr:
                    print(f"    Error: {stderr[:200]}")
                failed.append(run_name)
                completed += 1
                continue

            print(f"  ✓ Simulation completed")

            # Compute metrics
            state_log = run_log_dir / "state_log.jsonl"
            message_log = run_log_dir / "message_log.jsonl"
            result_file = results_path / f"{run_name}.json"

            if state_log.exists():
                success = compute_metrics(
                    state_log, message_log, result_file,
                    config_file=config_file,
                    nodes=nodes,
                    p_fail=p_fail,
                    p_drop=p_drop,
                    timeout=timeout
                )
                if success:
                    print(f"  ✓ Metrics computed")
                else:
                    print(f"  ✗ Metrics computation failed")
            else:
                print(f"  ✗ State log not found")

            completed += 1

    # Summary
    print(f"\n" + "=" * 60)
    print(f"SUMMARY")
    print(f"=" * 60)
    print(f"Completed: {completed}/{total}")
    print(f"Failed:    {len(failed)}")
    if failed:
        print(f"Failed runs: {', '.join(failed[:10])}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more")
    print(f"\nResults saved to: {results_path}")
    print(f"Run 'python3 {SCRIPT_DIR}/plots.py {results_path}' to generate plots")

# ============================================================
# Quick Experiment Presets
# ============================================================

PRESETS = {
    "quick": {
        "nodes": [4, 8, 16, 32],
        "p_fail": [0.02, 0.10],
        "p_drop": [0.0, 0.10],
        "timeout": [3],
    },
    "full": {
        "nodes": [5, 10, 15, 20],
        "p_fail": [0.02, 0.05, 0.10],
        "p_drop": [0.0, 0.05, 0.10],
        "timeout": [3],
    },
    "scaling": {
        "nodes": [5, 10, 15, 20, 25, 30],
        "p_fail": [0.05],
        "p_drop": [0.0],
        "timeout": [3],
    },
    "reliability": {
        "nodes": [10],
        "p_fail": [0.02, 0.05, 0.10, 0.15],
        "p_drop": [0.0, 0.05, 0.10, 0.15],
        "timeout": [3],
    },
    "timing": {
        "nodes": [10],
        "p_fail": [0.05],
        "p_drop": [0.0],
        "timeout": [2, 3, 4, 5],
    },
}

# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Bully simulation experiments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Run from project root (auto-finds executable in build/):
  python3 scripts/run_experiments.py --preset quick -o experiments

  # Specify executable explicitly:
  python3 scripts/run_experiments.py -e ./build/mpi_bully_sim --preset full

  # Custom parameters:
  python3 scripts/run_experiments.py --nodes 5 10 --p-fail 0.05 0.1

Project directory: {PROJECT_DIR}
"""
    )

    parser.add_argument("--executable", "-e", default=None,
                        help="Path to simulation executable (auto-detected if not specified)")
    parser.add_argument("--output", "-o", default="experiments",
                        help="Output directory")
    parser.add_argument("--preset", "-p", choices=list(PRESETS.keys()),
                        help="Use parameter preset")
    parser.add_argument("--runs", "-r", type=int, default=1,
                        help="Number of runs per configuration")
    parser.add_argument("--seed", type=int, default=12345,
                        help="Base random seed")
    parser.add_argument("--mpi-args", default=None,
                        help="Additional MPI arguments")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be run without running")

    # Custom parameter space
    parser.add_argument("--nodes", type=int, nargs="+", help="Node counts")
    parser.add_argument("--p-fail", type=float, nargs="+", help="Failure probabilities")
    parser.add_argument("--p-drop", type=float, nargs="+", help="Drop probabilities")
    parser.add_argument("--timeout", type=int, nargs="+", help="Election timeouts")

    args = parser.parse_args()

    # Find executable
    executable = args.executable
    if executable is None:
        executable = find_executable()
        if executable is None:
            print("Error: Could not find mpi_bully_sim executable.")
            print("Searched in:")
            print(f"  - {PROJECT_DIR / 'build' / 'mpi_bully_sim'}")
            print(f"  - {PROJECT_DIR / 'cmake-build-debug' / 'mpi_bully_sim'}")
            print(f"  - {PROJECT_DIR / 'cmake-build-release' / 'mpi_bully_sim'}")
            print("\nPlease build the project first or specify --executable path.")
            sys.exit(1)

    # Verify executable exists
    if not Path(executable).exists():
        print(f"Error: Executable not found: {executable}")
        sys.exit(1)

    # Determine parameters
    if args.preset:
        params = PRESETS[args.preset]
    else:
        params = DEFAULT_PARAMS.copy()

    # Override with command line args
    if args.nodes:
        params["nodes"] = args.nodes
    if args.p_fail:
        params["p_fail"] = args.p_fail
    if args.p_drop:
        params["p_drop"] = args.p_drop
    if args.timeout:
        params["timeout"] = args.timeout

    run_experiments(
        executable=executable,
        output_dir=args.output,
        nodes_list=params["nodes"],
        p_fail_list=params["p_fail"],
        p_drop_list=params["p_drop"],
        timeout_list=params["timeout"],
        num_runs=args.runs,
        seed_base=args.seed,
        mpi_args=args.mpi_args,
        dry_run=args.dry_run
    )
