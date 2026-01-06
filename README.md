# Bully Election Algorithm - MPI Simulation

A distributed systems simulation implementing the Bully Election Algorithm using OpenMPI. This project provides a tick-based simulation environment with configurable failure models, message dropping, and a D3.js visualizer for observing election dynamics.

## Building

### Prerequisites

- CMake 3.14+
- OpenMPI (or compatible MPI implementation)
- C++17 compatible compiler

### Build Steps

```bash
mkdir build && cd build
cmake ..
make
```

This will fetch `nlohmann/json` automatically via CMake's FetchContent.

### Running

```bash
# Run with 5 nodes (6 processes: 1 controller + 5 nodes)
mpirun -np 6 ./mpi_bully_sim -config ../config.json
```

The simulation produces three log files:
- `state_log.jsonl` - Node states per tick
- `message_log.jsonl` - All message events
- `debug_log.jsonl` - Debug messages from nodes (when verbose enabled)

## Features

### Core Simulation
- **Tick-based synchronous execution** - All nodes synchronized via MPI barriers
- **Pluggable failure models** - Extensible failure system with multiple implementations:
  - `NetworkFailure` - Network partitions where node runs but can't communicate
  - `CrashFailure` - Full node crash (for future use)
  - `NoFailure` - Disabled failures for testing pure algorithm behavior
- **Leader failure multiplier** - Leaders can be configured to fail more frequently
- **Message dropping** - Configurable probability for dropped messages
- **Random background traffic** - PING/ACK messages for network activity

### Bully Algorithm Implementation
- **ELECTION messages** - Sent to all higher-UID nodes when starting election
- **OK responses** - Higher-UID nodes respond to suppress lower-UID elections
- **COORDINATOR broadcast** - Election winner announces leadership to all nodes
- **HEARTBEAT protocol** - Leader sends periodic heartbeats; followers detect failure via timeout

### Correctness Features
- **Aggressive recovery** - Former leaders and high-UID nodes start elections on recovery
- **COORDINATOR rejection** - Nodes reject leadership claims from lower-UID nodes
- **Election timeout validation** - Warning when timeout is insufficient for message round-trips

### Visualization
- **D3.js visualizer** - Interactive graph showing nodes, states, and message flow
- **Autoload mode** - Automatically loads logs from the build directory
- **Playback controls** - Step through ticks or auto-play the simulation

### Validation
- **Python validation script** - Checks Bully algorithm correctness invariants
- **Multiple rules** - Leader uniqueness, consistency, maximality, protocol compliance

## Configuration

Edit `config.json` to customize the simulation:

```json
{
    "simulation": {
        "num_ticks": 50,
        "seed": 12345
    },
    "node": {
        "hb_period_ticks": 1,
        "hb_timeout_ticks": 3,
        "election_timeout_ticks": 3,
        "p_send": 0.30,
        "p_drop": 0.02,
        "max_recv_per_tick": 64
    },
    "failure": {
        "type": "network",
        "p_fail": 0.05,
        "leader_fail_multiplier": 2.0,
        "offline_durations": [1, 2, 3, 5],
        "offline_weights": [70, 20, 7, 3]
    },
    "logging": {
        "state_log_file": "state_log.jsonl",
        "message_log_file": "message_log.jsonl",
        "debug_log_file": "debug_log.jsonl",
        "verbose": true
    }
}
```

### Configuration Sections

| Section | Description |
|---------|-------------|
| `simulation` | Simulation parameters (ticks, seed) |
| `node` | Algorithm parameters (heartbeat, election, traffic) |
| `failure` | Failure model configuration (type, probabilities) |
| `logging` | Output file paths and verbosity |

### Failure Types

| Type | Description |
|------|-------------|
| `none` | No failures - pure algorithm testing |
| `network` | Network partitions - node runs but can't communicate |
| `crash` | Full node crash (reserved for future use) |

**Note**: For backwards compatibility, failure parameters can also be placed in the `node` section.

**Important**: `election_timeout_ticks` should be >= 3 to allow for message round-trips.

## Algorithm Approach

### System Model

This simulation implements the Bully Election Algorithm under a **crash-recovery** failure model with **synchronous tick-based execution**.

#### Key Design Decisions

1. **Synchrony Model**: Unlike real distributed systems, MPI processes execute in lockstep via `MPI_Barrier`. Each tick has distinct phases:
   - `tick_begin` - Update online/offline state
   - `tick_send` - Send heartbeats, elections, pings
   - `tick_recv` - Process incoming messages
   - `tick_end` - Check timeouts, declare victory

2. **Failure Model**: Pluggable failure system with separation of concerns:
   - **Network failures** (default): Node logic continues running but messages are silently dropped
   - **Crash failures** (future): Node fully stops - no internal logic runs
   - Failure state is injected into nodes via `set_can_communicate()`
   - Recovery happens automatically after weighted-random durations

3. **Message Delivery**: Messages are delivered within one tick (synchronous), but can be dropped with probability `p_drop`. No message reordering.

4. **Node Identity**: Each node has a unique identifier (UID) equal to its MPI rank (1 to N). Higher UID = higher priority for leadership.

### Election Protocol

#### Starting an Election

A node starts an election when:
- Heartbeat timeout expires (leader presumed dead)
- Recovering from offline with high UID or former leader status
- Receiving COORDINATOR from a lower-UID node (rejection triggers election)

#### Election Messages

1. **ELECTION**: Sent to all nodes with higher UID
2. **OK**: Response from higher-UID node, suppresses sender's election
3. **COORDINATOR**: Broadcast by election winner to announce leadership

#### Victory Conditions

A node wins the election when:
- It sends ELECTION messages and receives no OK responses within `election_timeout_ticks`
- It is the highest-UID node (no one to send ELECTION to)

Upon winning, the node:
- Sets itself as leader
- Broadcasts COORDINATOR to all other nodes
- Begins sending heartbeats

### Correctness Mechanisms

#### 1. Network Failure Semantics

With the `NetworkFailure` model, a "failed" node:
- Continues running its internal algorithm logic
- Cannot send or receive any messages (transport-level filtering)
- Detects leader failure via heartbeat timeout and starts elections
- Accumulates election/coordinator timeouts while partitioned

This models real-world network partitions where a node is isolated but not crashed.

#### 2. COORDINATOR Rejection

When receiving a COORDINATOR message:
```
if (coordinator_uid >= my_uid):
    accept_new_leader()
else:
    reject_and_start_election()  # I have higher priority
```

This prevents race conditions where a lower-UID node's COORDINATOR arrives after a higher-UID node has come online.

#### 3. COORDINATOR Timeout

When a node receives an OK response, it enters `waiting_for_coordinator_` state:
```
if (elapsed > election_timeout_ticks):
    waiting_for_coordinator_ = false
    start_election()  # Higher node failed - restart
```

This handles the case where a higher-UID node sends OK but then fails before sending COORDINATOR.

#### 4. Election Timeout

The election timeout must be >= 3 ticks to allow:
- Tick N: Send ELECTION
- Tick N+1: Higher node receives ELECTION, sends OK
- Tick N+2: Original node receives OK

With `election_timeout_ticks < 3`, a node may declare victory before OK messages arrive, leading to incorrect leaders.

### Message Flow Example

```
Tick 0: Node 5 is leader, sends HEARTBEAT
Tick 1: Node 5 goes offline
Tick 2: Nodes still have fresh heartbeat
Tick 3: Nodes still have fresh heartbeat
Tick 4: Node 3 detects timeout, starts election
        Node 3 sends ELECTION to nodes 4, 5
Tick 5: Node 4 receives ELECTION, sends OK to node 3
        Node 4 starts its own election (higher UID)
        Node 4 sends ELECTION to node 5 (offline, ignored)
Tick 6: Node 3 receives OK, stops election, waits for COORDINATOR
Tick 7: Node 4's election times out (no OK from node 5)
        Node 4 declares victory, broadcasts COORDINATOR
Tick 8: Node 3 receives COORDINATOR, accepts node 4 as leader
```

### Validation

Run the validation script to check correctness:

```bash
cd build
python3 ../validate_run.py --summary
```

Validation rules:
- **R1**: Leader uniqueness (at most one self-declared leader)
- **R2**: Leader consistency (all online nodes agree after stability)
- **R3**: Leader maximality (leader is highest online UID)
- **R4**: OK response protocol
- **R5**: COORDINATOR broadcast on victory
- **R7**: Heartbeat protocol compliance
- **R8**: Election termination

## Project Structure

```
Bully_MPI/
├── CMakeLists.txt
├── config.json
├── README.md
├── validate_run.py
├── src/
│   ├── main.cpp      # Simulation entry point, controller logic
│   ├── node.hpp      # Node class with Bully algorithm
│   ├── messages.hpp  # Message types and structures
│   ├── logger.hpp    # State, message, and debug logging
│   └── failure.hpp   # Pluggable failure models (Network, Crash, None)
├── scripts/
│   ├── run_experiments.py  # Batch experiment runner
│   └── metrics.py          # Compute election metrics from logs
└── visualizer/
    ├── index.html
    ├── graph.js      # D3.js visualization
    ├── playback.js   # Tick playback controls
    └── autoload.json # Visualizer configuration
```

### Architecture

The simulation uses a clean separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│                     main.cpp                            │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ Controller  │    │    Node     │    │   Failure   │  │
│  │  (rank 0)   │    │ (ranks 1-N) │    │   Model     │  │
│  └─────────────┘    └─────────────┘    └─────────────┘  │
│        │                   │                  │         │
│        │  MPI_Gather       │ set_can_communicate()      │
│        │◄──────────────────┤◄─────────────────┘         │
│        │                   │                            │
│        ▼                   │                            │
│  ┌─────────────┐           │                            │
│  │   Logger    │           │                            │
│  │ (JSONL out) │           │                            │
│  └─────────────┘           │                            │
└─────────────────────────────────────────────────────────┘
```

- **Node**: Pure algorithm logic - no knowledge of failure semantics
- **Failure**: Determines when communication is blocked
- **Controller**: Orchestrates simulation and collects logs
- **Logger**: Writes state, messages, and debug output to JSONL files

## Visualizer

Open `visualizer/index.html` in a browser. With autoload enabled, it reads logs from the build directory.

- **Green nodes**: Online
- **Gray nodes**: Offline
- **Gold border**: Current leader
- **Red border**: In election
- **Animated arrows**: Message flow between nodes

## Running Experiments

Use the experiment runner to batch multiple simulations across a parameter space:

```bash
# Run from project root (auto-finds executable in build/)
python3 scripts/run_experiments.py --preset quick -o experiments

# Or specify executable explicitly
python3 scripts/run_experiments.py -e ./build/mpi_bully_sim --preset full

# Custom parameters
python3 scripts/run_experiments.py --nodes 5 10 15 --p-fail 0.05 0.1
```

### Available Presets

| Preset | Description |
|--------|-------------|
| `quick` | Fast test: 4 node counts, 2 failure rates |
| `full` | Complete sweep: 4 node counts, 3 failure rates, 3 drop rates |
| `scaling` | Node scaling: 6 node counts, fixed failure rate |
| `reliability` | Reliability focus: fixed nodes, varying failure/drop |
| `timing` | Timeout testing: varying election timeouts |

### Metrics

Compute metrics from a single run:

```bash
python3 scripts/metrics.py path/to/state_log.jsonl
```

Metrics computed:
- **Election rate** - Elections started per 100 ticks
- **Agreement ratio** - Fraction of ticks with leader consensus
- **Convergence time** - Ticks to re-establish consensus after leader failure
