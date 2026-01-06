#!/usr/bin/env python3
"""
plots.py - Generate plots from Bully algorithm simulation results.

Plots:
  1. Metric Comparison Bar Chart - compare metrics across configurations
  2. Convergence Box Plot - distribution of convergence times
  3. Convergence Histogram - frequency distribution

Usage:
  python3 plots.py experiments/results -o plots
  python3 plots.py experiments/results -p boxplot --group-by num_nodes
"""

import json
import argparse
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from collections import defaultdict

# Style setup
try:
    plt.style.use('seaborn-v0_8-whitegrid')
except:
    plt.style.use('seaborn-whitegrid')

plt.rcParams.update({
    'figure.facecolor': 'white',
    'axes.facecolor': 'white',
    'font.size': 10,
    'axes.titlesize': 12,
    'axes.labelsize': 10,
})


def load_results(results_dir):
    """Load all JSON result files from directory."""
    results = {}
    results_path = Path(results_dir)
    
    for json_file in sorted(results_path.glob("*.json")):
        with open(json_file) as f:
            results[json_file.stem] = json.load(f)
    
    return results


def make_label(data):
    """Create readable label from config parameters."""
    parts = []
    if data.get('num_nodes'):
        parts.append(f"n={data['num_nodes']}")
    if data.get('p_fail') is not None:
        parts.append(f"pf={data['p_fail']}")
    if data.get('p_drop') is not None:
        parts.append(f"pd={data['p_drop']}")
    return "\n".join(parts) if parts else "config"


# ============================================================
# PLOT 1: Metric Comparison Bar Chart
# ============================================================
def plot_metric_comparison(results, output_path):
    """
    4-panel bar chart comparing:
    - Election Rate (per 100 ticks)
    - Agreement Ratio (%)
    - Average Convergence Time (ticks)
    - Leader Failures
    """
    configs = list(results.keys())
    n = len(configs)
    
    # Extract data
    election_rates = []
    agreement_ratios = []
    convergence_times = []
    leader_failures = []
    labels = []
    
    for c in configs:
        d = results[c]
        election_rates.append(d.get('election_rate_per_100', 0))
        agreement_ratios.append(d.get('agreement_ratio', 0) * 100)
        convergence_times.append(d.get('avg_convergence_time', 0))
        leader_failures.append(d.get('leader_failures', 0))
        labels.append(make_label(d))
    
    # Create figure
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    x = np.arange(n)
    colors = plt.cm.viridis(np.linspace(0.25, 0.75, n))
    
    # Election Rate
    ax = axes[0, 0]
    bars = ax.bar(x, election_rates, color=colors)
    ax.axhline(np.mean(election_rates), color='red', linestyle='--', alpha=0.6, label=f'Mean: {np.mean(election_rates):.1f}')
    ax.set_ylabel('Elections per 100 ticks')
    ax.set_title('Election Rate', fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.legend(loc='upper right')
    
    # Agreement Ratio
    ax = axes[0, 1]
    bars = ax.bar(x, agreement_ratios, color=colors)
    ax.axhline(90, color='red', linestyle='--', alpha=0.6, label='90% threshold')
    ax.set_ylabel('Agreement (%)')
    ax.set_title('Agreement Ratio', fontweight='bold')
    ax.set_ylim(0, 105)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.legend(loc='lower right')
    
    # Convergence Time
    ax = axes[1, 0]
    bars = ax.bar(x, convergence_times, color=colors)
    ax.axhline(np.mean(convergence_times), color='red', linestyle='--', alpha=0.6, label=f'Mean: {np.mean(convergence_times):.2f}')
    ax.set_ylabel('Ticks')
    ax.set_title('Average Convergence Time', fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.legend(loc='upper right')
    
    # Leader Failures
    ax = axes[1, 1]
    bars = ax.bar(x, leader_failures, color=colors)
    ax.axhline(np.mean(leader_failures), color='red', linestyle='--', alpha=0.6, label=f'Mean: {np.mean(leader_failures):.1f}')
    ax.set_ylabel('Failures')
    ax.set_title('Leader Failures', fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.legend(loc='upper right')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


# ============================================================
# PLOT 2: Convergence Time Box Plot
# ============================================================
def plot_convergence_boxplot(results, output_path, group_by=None):
    """
    Box plot showing convergence time distributions.
    
    group_by: None (per config) or 'num_nodes', 'p_fail', 'p_drop'
    """
    if group_by:
        # Group by parameter value
        grouped = defaultdict(list)
        for config, data in results.items():
            key = data.get(group_by)
            if key is not None:
                times = data.get('convergence_times', [])
                grouped[key].extend(times)
        
        if not grouped:
            print(f"No data for group_by={group_by}")
            return
        
        sorted_keys = sorted(grouped.keys())
        plot_data = [grouped[k] for k in sorted_keys]
        labels = [str(k) for k in sorted_keys]
        title = f'Convergence Time by {group_by.replace("_", " ").title()}'
        xlabel = group_by.replace("_", " ").title()
    else:
        # Per configuration
        configs = list(results.keys())
        plot_data = [results[c].get('convergence_times', []) for c in configs]
        labels = [make_label(results[c]) for c in configs]
        title = 'Convergence Time Distribution'
        xlabel = 'Configuration'
    
    # Filter empty
    filtered = [(d, l) for d, l in zip(plot_data, labels) if len(d) > 0]
    if not filtered:
        print("No convergence data available")
        return
    
    plot_data, labels = zip(*filtered)
    n = len(plot_data)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(max(10, n * 0.8), 6))
    
    bp = ax.boxplot(plot_data, patch_artist=True, labels=labels)
    
    # Color boxes
    colors = plt.cm.viridis(np.linspace(0.25, 0.75, n))
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    # Add mean markers
    means = [np.mean(d) for d in plot_data]
    ax.scatter(range(1, n + 1), means, color='red', marker='D', s=50, zorder=5, label='Mean')
    
    ax.set_xlabel(xlabel)
    ax.set_ylabel('Convergence Time (ticks)')
    ax.set_title(title, fontweight='bold')
    ax.legend(loc='upper right')
    
    if n > 6:
        plt.xticks(rotation=45, ha='right')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


# ============================================================
# PLOT 3: Convergence Time Histogram
# ============================================================
def plot_convergence_histogram(results, output_path, group_by=None):
    """
    Histogram of convergence times.
    
    group_by: None (all combined) or 'num_nodes', 'p_fail', 'p_drop'
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    
    if group_by:
        # Overlay histograms by parameter value
        grouped = defaultdict(list)
        for config, data in results.items():
            key = data.get(group_by)
            if key is not None:
                times = data.get('convergence_times', [])
                grouped[key].extend(times)
        
        if not grouped:
            print(f"No data for group_by={group_by}")
            return
        
        sorted_keys = sorted(grouped.keys())
        colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(sorted_keys)))
        
        # Find global max for consistent bins
        all_times = [t for times in grouped.values() for t in times]
        bins = np.linspace(0, max(all_times) + 1, 25)
        
        for i, key in enumerate(sorted_keys):
            if grouped[key]:
                ax.hist(grouped[key], bins=bins, alpha=0.5, 
                       label=f'{group_by}={key}', color=colors[i], edgecolor='black', linewidth=0.5)
        
        ax.set_title(f'Convergence Time by {group_by.replace("_", " ").title()}', fontweight='bold')
        ax.legend(loc='upper right')
    
    else:
        # All data combined
        all_times = []
        for data in results.values():
            all_times.extend(data.get('convergence_times', []))
        
        if not all_times:
            print("No convergence data")
            return
        
        ax.hist(all_times, bins=30, color='steelblue', alpha=0.7, edgecolor='black')
        
        mean_val = np.mean(all_times)
        median_val = np.median(all_times)
        ax.axvline(mean_val, color='red', linestyle='--', linewidth=2, label=f'Mean: {mean_val:.2f}')
        ax.axvline(median_val, color='orange', linestyle='--', linewidth=2, label=f'Median: {median_val:.2f}')
        
        ax.set_title('Convergence Time Distribution', fontweight='bold')
        ax.legend(loc='upper right')
    
    ax.set_xlabel('Convergence Time (ticks)')
    ax.set_ylabel('Frequency')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


# ============================================================
# PLOT 4: Scaling Analysis
# ============================================================
def plot_scaling(results, output_path):
    """
    Line plots showing how metrics scale with number of nodes.
    """
    # Group by num_nodes
    by_nodes = defaultdict(list)
    for config, data in results.items():
        n = data.get('num_nodes')
        if n is not None:
            by_nodes[n].append(data)
    
    if len(by_nodes) < 2:
        print("Need at least 2 different node counts for scaling plot")
        return
    
    sorted_nodes = sorted(by_nodes.keys())
    
    # Calculate means and stds
    def stats(key):
        means = []
        stds = []
        for n in sorted_nodes:
            vals = [d.get(key, 0) for d in by_nodes[n]]
            means.append(np.mean(vals))
            stds.append(np.std(vals) if len(vals) > 1 else 0)
        return means, stds
    
    election_m, election_s = stats('election_rate_per_100')
    agreement_m, agreement_s = stats('agreement_ratio')
    agreement_m = [v * 100 for v in agreement_m]
    convergence_m, convergence_s = stats('avg_convergence_time')
    
    # Plot
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    
    ax = axes[0]
    ax.errorbar(sorted_nodes, election_m, yerr=election_s, fmt='o-', 
                color='steelblue', linewidth=2, markersize=8, capsize=4)
    ax.set_xlabel('Number of Nodes')
    ax.set_ylabel('Elections per 100 ticks')
    ax.set_title('Election Rate', fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    ax = axes[1]
    ax.errorbar(sorted_nodes, agreement_m, fmt='o-',
                color='seagreen', linewidth=2, markersize=8, capsize=4)
    ax.set_xlabel('Number of Nodes')
    ax.set_ylabel('Agreement (%)')
    ax.set_title('Agreement Ratio', fontweight='bold')
    ax.set_ylim(0, 105)
    ax.grid(True, alpha=0.3)
    
    ax = axes[2]
    ax.errorbar(sorted_nodes, convergence_m, yerr=convergence_s, fmt='o-',
                color='coral', linewidth=2, markersize=8, capsize=4)
    ax.set_xlabel('Number of Nodes')
    ax.set_ylabel('Ticks')
    ax.set_title('Convergence Time', fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


# ============================================================
# PLOT 5: Heatmap (p_fail vs p_drop)
# ============================================================
def plot_heatmap(results, metric, output_path):
    """
    Heatmap showing metric values across p_fail x p_drop grid.
    """
    # Build grid
    grid = {}
    for config, data in results.items():
        pf = data.get('p_fail')
        pd = data.get('p_drop')
        val = data.get(metric)
        
        if pf is not None and pd is not None and val is not None:
            if metric == 'agreement_ratio':
                val *= 100
            grid[(pf, pd)] = val
    
    if not grid:
        print(f"No grid data for {metric}")
        return
    
    # Get unique values
    p_fails = sorted(set(k[0] for k in grid.keys()))
    p_drops = sorted(set(k[1] for k in grid.keys()))
    
    # Build matrix
    matrix = np.full((len(p_fails), len(p_drops)), np.nan)
    for i, pf in enumerate(p_fails):
        for j, pd in enumerate(p_drops):
            if (pf, pd) in grid:
                matrix[i, j] = grid[(pf, pd)]
    
    # Plot
    fig, ax = plt.subplots(figsize=(8, 6))
    
    # Choose colormap
    if metric in ['election_rate_per_100', 'avg_convergence_time', 'leader_failures']:
        cmap = 'RdYlGn_r'  # Red = bad (high)
    else:
        cmap = 'RdYlGn'    # Green = good (high)
    
    im = ax.imshow(matrix, cmap=cmap, aspect='auto', origin='lower')
    
    # Labels
    ax.set_xticks(range(len(p_drops)))
    ax.set_xticklabels([f'{pd:.2f}' for pd in p_drops])
    ax.set_yticks(range(len(p_fails)))
    ax.set_yticklabels([f'{pf:.2f}' for pf in p_fails])
    ax.set_xlabel('p_drop')
    ax.set_ylabel('p_fail')
    
    # Title
    titles = {
        'election_rate_per_100': 'Election Rate (per 100 ticks)',
        'agreement_ratio': 'Agreement Ratio (%)',
        'avg_convergence_time': 'Avg Convergence Time (ticks)',
        'leader_failures': 'Leader Failures'
    }
    ax.set_title(titles.get(metric, metric), fontweight='bold')
    
    # Add value annotations
    for i in range(len(p_fails)):
        for j in range(len(p_drops)):
            val = matrix[i, j]
            if not np.isnan(val):
                color = 'white' if val > np.nanmedian(matrix) else 'black'
                ax.text(j, i, f'{val:.1f}', ha='center', va='center', 
                       color=color, fontweight='bold', fontsize=9)
    
    plt.colorbar(im, ax=ax)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


# ============================================================
# Generate All Plots
# ============================================================
def generate_all(results, output_dir):
    """Generate all plots."""
    out = Path(output_dir)
    out.mkdir(exist_ok=True)
    
    print(f"\n{'='*50}")
    print(f"Generating plots in: {output_dir}/")
    print(f"{'='*50}\n")
    
    # 1. Metric comparison
    plot_metric_comparison(results, out / 'metric_comparison.png')
    
    # 2. Box plots
    plot_convergence_boxplot(results, out / 'convergence_boxplot.png')
    plot_convergence_boxplot(results, out / 'convergence_by_nodes.png', group_by='num_nodes')
    plot_convergence_boxplot(results, out / 'convergence_by_pfail.png', group_by='p_fail')
    plot_convergence_boxplot(results, out / 'convergence_by_pdrop.png', group_by='p_drop')
    
    # 3. Histograms
    plot_convergence_histogram(results, out / 'convergence_histogram.png')
    plot_convergence_histogram(results, out / 'histogram_by_nodes.png', group_by='num_nodes')
    plot_convergence_histogram(results, out / 'histogram_by_pfail.png', group_by='p_fail')
    plot_convergence_histogram(results, out / 'histogram_by_pdrop.png', group_by='p_drop')
    
    # 4. Scaling
    plot_scaling(results, out / 'scaling.png')
    
    # 5. Heatmaps
    plot_heatmap(results, 'election_rate_per_100', out / 'heatmap_election.png')
    plot_heatmap(results, 'agreement_ratio', out / 'heatmap_agreement.png')
    plot_heatmap(results, 'avg_convergence_time', out / 'heatmap_convergence.png')
    
    print(f"\n{'='*50}")
    print(f"Done! Generated {len(list(out.glob('*.png')))} plots")
    print(f"{'='*50}")


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='Generate plots from Bully simulation results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 plots.py experiments/results
  python3 plots.py experiments/results -o my_plots
  python3 plots.py experiments/results -p boxplot -g num_nodes
  python3 plots.py experiments/results -p heatmap -m agreement_ratio
        """
    )
    
    parser.add_argument('results_dir', help='Directory with result JSON files')
    parser.add_argument('-o', '--output', default='plots', help='Output directory')
    parser.add_argument('-p', '--plot', 
                        choices=['all', 'comparison', 'boxplot', 'histogram', 'scaling', 'heatmap'],
                        default='all', help='Plot type')
    parser.add_argument('-g', '--group-by',
                        choices=['num_nodes', 'p_fail', 'p_drop'],
                        help='Group by parameter')
    parser.add_argument('-m', '--metric',
                        choices=['election_rate_per_100', 'agreement_ratio', 'avg_convergence_time', 'leader_failures'],
                        default='election_rate_per_100',
                        help='Metric for heatmap')
    
    args = parser.parse_args()
    
    # Load results
    results = load_results(args.results_dir)
    if not results:
        print(f"Error: No JSON files found in {args.results_dir}")
        return 1
    
    print(f"Loaded {len(results)} results")
    
    # Show data summary
    nodes = sorted(set(d.get('num_nodes') for d in results.values() if d.get('num_nodes')))
    pfails = sorted(set(d.get('p_fail') for d in results.values() if d.get('p_fail') is not None))
    pdrops = sorted(set(d.get('p_drop') for d in results.values() if d.get('p_drop') is not None))
    
    print(f"  num_nodes: {nodes}")
    print(f"  p_fail:    {pfails}")
    print(f"  p_drop:    {pdrops}")
    
    # Create output directory
    out = Path(args.output)
    out.mkdir(exist_ok=True)
    
    # Generate requested plots
    if args.plot == 'all':
        generate_all(results, args.output)
    elif args.plot == 'comparison':
        plot_metric_comparison(results, out / 'metric_comparison.png')
    elif args.plot == 'boxplot':
        plot_convergence_boxplot(results, out / 'convergence_boxplot.png', args.group_by)
    elif args.plot == 'histogram':
        plot_convergence_histogram(results, out / 'convergence_histogram.png', args.group_by)
    elif args.plot == 'scaling':
        plot_scaling(results, out / 'scaling.png')
    elif args.plot == 'heatmap':
        plot_heatmap(results, args.metric, out / f'heatmap_{args.metric}.png')
    
    return 0


if __name__ == '__main__':
    exit(main())