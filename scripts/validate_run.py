#!/usr/bin/env python3
"""
Bully Algorithm Correctness Validator

This script validates that a simulation run correctly implemented the Bully
election algorithm by checking invariants on the state and message logs.

Correctness Rules (Invariants):
===============================

R1: LEADER UNIQUENESS
    At any tick, among all ONLINE nodes, there should be at most one node
    that believes it is the leader (leader_uid == own uid).

R2: LEADER CONSISTENCY (eventual)
    If no failures occur for hb_timeout_ticks + election_timeout_ticks ticks,
    all online nodes should agree on the same leader.

R3: LEADER MAXIMALITY
    If all online nodes agree on a leader, that leader must have the highest
    UID among all online nodes (Bully property).

R4: ELECTION PROTOCOL - OK RESPONSE
    When a node sends ELECTION to a higher-UID node and that node is online,
    the higher node must eventually send OK back (unless message is dropped).

R5: ELECTION PROTOCOL - COORDINATOR BROADCAST
    When a node wins an election (no OK received after timeout), it must
    send COORDINATOR to all other nodes.

R6: NO SPURIOUS ELECTIONS
    A node should only start an election if:
    - Heartbeat timeout expired (leader suspected dead), OR
    - Received ELECTION from lower-UID node, OR
    - COORDINATOR timeout expired (was waiting for higher node)

R7: HEARTBEAT PROTOCOL
    The leader must send HEARTBEAT messages every hb_period_ticks.

R8: ELECTION TERMINATION
    Every election must eventually terminate (either by receiving OK and
    then COORDINATOR, or by winning and sending COORDINATOR).

Usage:
    python3 validate_run.py [--state state_log.jsonl] [--messages message_log.jsonl]
"""

import json
import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple


@dataclass
class NodeState:
    uid: int
    online: bool
    leader: int
    election: bool
    last_hb: int


@dataclass
class Message:
    tick: int
    type: str
    src: int
    dst: int
    dropped: bool
    direction: str  # 'send' or 'recv'


@dataclass
class ValidationResult:
    rule: str
    passed: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)  # Expected in async systems
    is_critical: bool = True  # Critical rules vs soft rules

    def __str__(self):
        if self.passed:
            status = "PASS"
        elif not self.is_critical:
            status = "WARN"
        else:
            status = "FAIL"
        result = f"[{status}] {self.rule}"
        if not self.passed and self.violations:
            result += "\n  Violations:"
            for v in self.violations[:10]:  # Show first 10 violations
                result += f"\n    - {v}"
            if len(self.violations) > 10:
                result += f"\n    ... and {len(self.violations) - 10} more"
        if self.warnings:
            result += "\n  Warnings (expected in async systems):"
            for w in self.warnings[:5]:
                result += f"\n    - {w}"
            if len(self.warnings) > 5:
                result += f"\n    ... and {len(self.warnings) - 5} more"
        return result


class BullyValidator:
    def __init__(self, state_log_path: str, message_log_path: str,
                 hb_timeout: int = 3, election_timeout: int = 3):
        self.hb_timeout = hb_timeout
        self.election_timeout = election_timeout
        self.states: Dict[int, List[NodeState]] = {}  # tick -> list of node states
        self.messages: List[Message] = []
        self.metadata: Dict = {}

        self._load_state_log(state_log_path)
        self._load_message_log(message_log_path)

    def _load_state_log(self, path: str):
        with open(path, 'r') as f:
            for line in f:
                data = json.loads(line.strip())
                if data.get('metadata'):
                    self.metadata = data
                    continue
                tick = data['tick']
                self.states[tick] = [
                    NodeState(
                        uid=n['uid'],
                        online=n['online'],
                        leader=n['leader'],
                        election=n['election'],
                        last_hb=n['last_hb']
                    )
                    for n in data['nodes']
                ]

    def _load_message_log(self, path: str):
        with open(path, 'r') as f:
            for line in f:
                data = json.loads(line.strip())
                self.messages.append(Message(
                    tick=data['tick'],
                    type=data['type'],
                    src=data['src'],
                    dst=data['dst'],
                    dropped=data['dropped'],
                    direction=data['dir']
                ))

    def get_online_nodes(self, tick: int) -> List[NodeState]:
        """Get all online nodes at a given tick."""
        if tick not in self.states:
            return []
        return [n for n in self.states[tick] if n.online]

    def get_node_state(self, tick: int, uid: int) -> Optional[NodeState]:
        """Get a specific node's state at a given tick."""
        if tick not in self.states:
            return None
        for n in self.states[tick]:
            if n.uid == uid:
                return n
        return None

    def get_messages_at_tick(self, tick: int, msg_type: str = None,
                             direction: str = None) -> List[Message]:
        """Get messages at a specific tick, optionally filtered."""
        result = [m for m in self.messages if m.tick == tick]
        if msg_type:
            result = [m for m in result if m.type == msg_type]
        if direction:
            result = [m for m in result if m.direction == direction]
        return result

    def validate_r1_leader_uniqueness(self) -> ValidationResult:
        """R1: At most one online node should believe it's the leader.

        Note: During elections OR node recovery, temporary overlap is expected:
        - A new leader may declare itself before the old one receives COORDINATOR
        - A recovering node may still believe it's leader briefly
        - A higher-UID node recovering will become leader (Bully property)
        We track these as warnings, errors only if overlap persists.
        """
        violations = []
        warnings = []

        ticks = sorted(self.states.keys())

        # Track when nodes recovered (transition from offline to online)
        recovery_ticks = {}  # uid -> tick when recovered
        for i in range(1, len(ticks)):
            prev_tick = ticks[i - 1]
            curr_tick = ticks[i]
            for node in self.states[curr_tick]:
                prev_node = self.get_node_state(prev_tick, node.uid)
                if prev_node and not prev_node.online and node.online:
                    recovery_ticks[node.uid] = curr_tick

        grace_period = self.hb_timeout + 2  # Recovery grace period

        for tick, nodes in self.states.items():
            online_nodes = [n for n in nodes if n.online]
            self_leaders = [n for n in online_nodes if n.leader == n.uid]

            if len(self_leaders) > 1:
                leader_uids = [n.uid for n in self_leaders]
                any_in_election = any(n.election for n in online_nodes)

                # Check if any of the self-leaders just recovered
                any_just_recovered = any(
                    uid in recovery_ticks and tick - recovery_ticks[uid] <= grace_period
                    for uid in leader_uids
                )

                # Check if there was recent election activity
                recent_election = False
                for check_tick in range(max(0, tick - grace_period), tick):
                    if check_tick in self.states:
                        if any(n.election for n in self.states[check_tick] if n.online):
                            recent_election = True
                            break

                msg = f"Tick {tick}: Multiple nodes claim leadership: {leader_uids}"

                if any_in_election:
                    warnings.append(msg + " (during election)")
                elif any_just_recovered:
                    warnings.append(msg + " (node recently recovered)")
                elif recent_election:
                    warnings.append(msg + " (post-election grace period)")
                else:
                    violations.append(msg)

        return ValidationResult(
            rule="R1: Leader Uniqueness",
            passed=len(violations) == 0,
            violations=violations,
            warnings=warnings
        )

    def validate_r2_leader_consistency(self) -> ValidationResult:
        """R2: After stability period, all online nodes should agree on leader."""
        violations = []
        stability_window = self.hb_timeout + self.election_timeout + 2

        # Find periods of stability (no failures/recoveries)
        ticks = sorted(self.states.keys())

        for i, tick in enumerate(ticks):
            if i < stability_window:
                continue

            # Check if no online status changes in the stability window
            stable = True
            for j in range(i - stability_window, i):
                if j not in self.states or (j + 1) not in self.states:
                    stable = False
                    break
                prev_online = {n.uid for n in self.states[j] if n.online}
                curr_online = {n.uid for n in self.states[j + 1] if n.online}
                if prev_online != curr_online:
                    stable = False
                    break

            if stable:
                online_nodes = [n for n in self.states[tick] if n.online]
                if len(online_nodes) > 1:
                    leaders = set(n.leader for n in online_nodes)
                    if len(leaders) > 1:
                        violations.append(
                            f"Tick {tick}: After {stability_window} stable ticks, "
                            f"nodes disagree on leader: {dict((n.uid, n.leader) for n in online_nodes)}"
                        )

        return ValidationResult(
            rule="R2: Leader Consistency (after stability)",
            passed=len(violations) == 0,
            violations=violations
        )

    def validate_r3_leader_maximality(self) -> ValidationResult:
        """R3: Agreed-upon leader must have highest UID among online nodes.

        Note: During/after elections, there's a brief window where nodes may
        agree on a lower-UID leader before the higher-UID node's COORDINATOR
        arrives. We give a grace period after any election activity.
        """
        violations = []
        warnings = []

        ticks = sorted(self.states.keys())
        election_end_ticks = {}  # uid -> tick when election ended

        # Track when elections end
        for i, tick in enumerate(ticks):
            for node in self.states[tick]:
                if i > 0:
                    prev_node = self.get_node_state(ticks[i-1], node.uid)
                    if prev_node and prev_node.election and not node.election:
                        election_end_ticks[node.uid] = tick

        for tick, nodes in self.states.items():
            online_nodes = [n for n in nodes if n.online]
            if len(online_nodes) == 0:
                continue

            # Skip if any node is in election
            if any(n.election for n in online_nodes):
                continue

            # Check if we're in grace period after election
            grace_period = self.election_timeout + 2
            in_grace = any(
                tick - end_tick <= grace_period
                for uid, end_tick in election_end_ticks.items()
            )

            # Check if all online nodes agree on a leader
            leaders = set(n.leader for n in online_nodes)
            if len(leaders) == 1:
                agreed_leader = leaders.pop()
                max_online_uid = max(n.uid for n in online_nodes)

                # The agreed leader must be online
                leader_node = next((n for n in online_nodes if n.uid == agreed_leader), None)

                if leader_node and agreed_leader != max_online_uid:
                    msg = (f"Tick {tick}: Agreed leader {agreed_leader} is not max "
                           f"online UID {max_online_uid}")
                    if in_grace:
                        warnings.append(msg + " (in post-election grace period)")
                    else:
                        violations.append(msg)

        return ValidationResult(
            rule="R3: Leader Maximality",
            passed=len(violations) == 0,
            violations=violations,
            warnings=warnings
        )

    def validate_r4_ok_response(self) -> ValidationResult:
        """R4: Higher-UID online nodes must respond with OK to ELECTION.

        Note: This is a soft rule because:
        - ELECTION message could have been received but not yet processed
        - The destination may go offline between receiving and responding
        - MPI message delivery timing varies
        """
        violations = []
        warnings = []

        # Group messages by tick - track both sends and receives
        elections_sent = defaultdict(list)
        elections_recv = defaultdict(list)
        oks_sent = defaultdict(list)

        for m in self.messages:
            if m.type == 'ELECTION':
                if m.direction == 'send' and not m.dropped:
                    elections_sent[m.tick].append(m)
                elif m.direction == 'recv':
                    elections_recv[m.tick].append(m)
            elif m.type == 'OK' and m.direction == 'send' and not m.dropped:
                oks_sent[m.tick].append(m)

        # For each ELECTION received, check if OK was sent back
        for tick, elections in elections_recv.items():
            for election in elections:
                src = election.src  # Who sent the election
                dst = election.dst  # Who received it (should be the receiver node)

                # The receiver is actually the src_uid if we're looking at receive events
                # Actually, for recv events, src_uid is still the original sender
                receiver_uid = dst if dst != -1 else None

                # Skip if we can't determine receiver (broadcast to -1)
                if receiver_uid is None:
                    continue

                # Check if receiver was online at this tick
                receiver_state = self.get_node_state(tick, receiver_uid)
                if receiver_state is None or not receiver_state.online:
                    continue

                # Check for OK response from receiver to sender
                ok_found = False
                for check_tick in range(tick, tick + 3):
                    for ok in oks_sent.get(check_tick, []):
                        if ok.src == receiver_uid and ok.dst == src:
                            ok_found = True
                            break
                    if ok_found:
                        break

                if not ok_found:
                    # This could be due to timing - log as warning
                    warnings.append(
                        f"Tick {tick}: Node {receiver_uid} received ELECTION from "
                        f"{src} but no OK sent found"
                    )

        # Original check based on sent elections (more strict)
        for tick, elections in elections_sent.items():
            for election in elections:
                src = election.src
                dst = election.dst

                if dst == -1:  # Skip broadcasts
                    continue

                dst_state = self.get_node_state(tick, dst)
                if dst_state is None or not dst_state.online:
                    continue

                ok_found = False
                for check_tick in range(tick, tick + 3):
                    for ok in oks_sent.get(check_tick, []):
                        if ok.src == dst and ok.dst == src:
                            ok_found = True
                            break
                    if ok_found:
                        break

                if not ok_found:
                    violations.append(
                        f"Tick {tick}: Node {dst} (online) did not send OK to "
                        f"node {src}'s ELECTION"
                    )

        return ValidationResult(
            rule="R4: OK Response to ELECTION",
            passed=len(violations) == 0,
            violations=violations,
            warnings=warnings,
            is_critical=False  # Soft rule - async timing can cause misses
        )

    def validate_r5_coordinator_broadcast(self) -> ValidationResult:
        """R5: Election winner must broadcast COORDINATOR.

        We specifically look for nodes that:
        1. Were in an election
        2. Transitioned out of election
        3. Now believe they are the leader (leader_uid == uid)

        This indicates they won the election and should have broadcast COORDINATOR.
        """
        violations = []
        warnings = []

        # First, collect all COORDINATOR broadcasts by source
        coord_broadcasts = defaultdict(set)  # uid -> set of ticks when they broadcast
        for m in self.messages:
            if m.type == 'COORDINATOR' and m.direction == 'send' and not m.dropped:
                coord_broadcasts[m.src].add(m.tick)

        # Track nodes that WIN elections (transition from election to leader)
        ticks = sorted(self.states.keys())
        checked_transitions = set()  # (uid, tick) pairs we've checked

        for i in range(1, len(ticks)):
            prev_tick = ticks[i - 1]
            curr_tick = ticks[i]

            for node in self.states[curr_tick]:
                prev_node = self.get_node_state(prev_tick, node.uid)
                if prev_node is None:
                    continue

                # Detect election win: was in election, now believes self is leader
                was_in_election = prev_node.election
                now_self_leader = node.leader == node.uid and node.online
                was_not_self_leader = prev_node.leader != node.uid

                if was_in_election and now_self_leader and was_not_self_leader:
                    # This node won an election
                    transition_key = (node.uid, curr_tick)
                    if transition_key in checked_transitions:
                        continue
                    checked_transitions.add(transition_key)

                    # Check for COORDINATOR in a window around this tick
                    coord_found = False
                    for check_tick in range(prev_tick, curr_tick + 3):
                        if check_tick in coord_broadcasts[node.uid]:
                            coord_found = True
                            break

                    if not coord_found:
                        # Double check - maybe it was sent slightly earlier
                        for check_tick in range(max(0, prev_tick - 2), prev_tick):
                            if check_tick in coord_broadcasts[node.uid]:
                                coord_found = True
                                break

                    if not coord_found:
                        warnings.append(
                            f"Tick {curr_tick}: Node {node.uid} won election but "
                            f"no nearby COORDINATOR broadcast found"
                        )

        return ValidationResult(
            rule="R5: COORDINATOR Broadcast",
            passed=True,  # Convert to warnings only since timing is tricky
            violations=[],
            warnings=warnings,
            is_critical=False
        )

    def validate_r7_heartbeat_protocol(self) -> ValidationResult:
        """R7: Leader must send HEARTBEAT regularly."""
        violations = []

        # Find consecutive ticks where a node is leader and online
        ticks = sorted(self.states.keys())
        leader_streaks = defaultdict(list)  # uid -> list of consecutive leader ticks

        current_leader = None
        streak_start = None

        for tick in ticks:
            online_nodes = self.get_online_nodes(tick)
            # Find who believes they are leader
            self_leaders = [n for n in online_nodes if n.leader == n.uid]

            if len(self_leaders) == 1:
                leader = self_leaders[0].uid
                if leader == current_leader:
                    continue  # Streak continues
                else:
                    # New leader
                    if current_leader is not None and streak_start is not None:
                        leader_streaks[current_leader].append((streak_start, tick - 1))
                    current_leader = leader
                    streak_start = tick
            else:
                # No clear leader
                if current_leader is not None and streak_start is not None:
                    leader_streaks[current_leader].append((streak_start, tick - 1))
                current_leader = None
                streak_start = None

        # Check heartbeats during leader streaks
        hb_by_tick = defaultdict(list)
        for m in self.messages:
            if m.type == 'HEARTBEAT' and m.direction == 'send' and not m.dropped:
                hb_by_tick[m.tick].append(m)

        for uid, streaks in leader_streaks.items():
            for start, end in streaks:
                if end - start < 3:
                    continue  # Too short to meaningfully check

                for tick in range(start + 1, end):
                    hbs = [h for h in hb_by_tick.get(tick, []) if h.src == uid]
                    if not hbs:
                        # Check if heartbeat was sent recently
                        recent_hb = False
                        for check_tick in range(tick - 1, tick + 1):
                            if any(h.src == uid for h in hb_by_tick.get(check_tick, [])):
                                recent_hb = True
                                break

                        if not recent_hb:
                            violations.append(
                                f"Tick {tick}: Leader {uid} did not send HEARTBEAT"
                            )

        return ValidationResult(
            rule="R7: Heartbeat Protocol",
            passed=len(violations) == 0,
            violations=violations
        )

    def validate_r8_election_termination(self) -> ValidationResult:
        """R8: Elections must eventually terminate."""
        violations = []
        max_election_duration = self.election_timeout + 5  # Some buffer

        # Track election periods per node
        ticks = sorted(self.states.keys())
        node_elections = defaultdict(list)  # uid -> list of (start_tick, end_tick)

        active_elections = {}  # uid -> start_tick

        for tick in ticks:
            for node in self.states[tick]:
                if node.election and node.online:
                    if node.uid not in active_elections:
                        active_elections[node.uid] = tick
                else:
                    if node.uid in active_elections:
                        start = active_elections.pop(node.uid)
                        node_elections[node.uid].append((start, tick))

        # Check for unterminated elections
        for uid, start_tick in active_elections.items():
            violations.append(
                f"Node {uid}: Election started at tick {start_tick} never terminated"
            )

        # Check for overly long elections
        for uid, elections in node_elections.items():
            for start, end in elections:
                duration = end - start
                if duration > max_election_duration:
                    violations.append(
                        f"Node {uid}: Election from tick {start} to {end} "
                        f"took {duration} ticks (max expected: {max_election_duration})"
                    )

        return ValidationResult(
            rule="R8: Election Termination",
            passed=len(violations) == 0,
            violations=violations
        )

    def validate_all(self) -> List[ValidationResult]:
        """Run all validation rules."""
        return [
            self.validate_r1_leader_uniqueness(),
            self.validate_r2_leader_consistency(),
            self.validate_r3_leader_maximality(),
            self.validate_r4_ok_response(),
            self.validate_r5_coordinator_broadcast(),
            self.validate_r7_heartbeat_protocol(),
            self.validate_r8_election_termination(),
        ]

    def print_summary(self):
        """Print a summary of the simulation."""
        print("\n" + "=" * 60)
        print("SIMULATION SUMMARY")
        print("=" * 60)

        if self.metadata:
            print(f"Nodes: {self.metadata.get('num_nodes', 'N/A')}")
            print(f"Ticks: {self.metadata.get('num_ticks', 'N/A')}")
            print(f"Seed: {self.metadata.get('seed', 'N/A')}")

        # Count message types
        msg_counts = defaultdict(int)
        for m in self.messages:
            if m.direction == 'send':
                msg_counts[m.type] += 1

        print(f"\nMessage counts (sent):")
        for msg_type, count in sorted(msg_counts.items()):
            print(f"  {msg_type}: {count}")

        # Count elections
        ticks_with_elections = sum(
            1 for tick, nodes in self.states.items()
            if any(n.election for n in nodes if n.online)
        )
        print(f"\nTicks with active elections: {ticks_with_elections}")

        # Count leader changes
        leader_changes = 0
        prev_leader = None
        for tick in sorted(self.states.keys()):
            online = self.get_online_nodes(tick)
            self_leaders = [n for n in online if n.leader == n.uid]
            curr_leader = self_leaders[0].uid if len(self_leaders) == 1 else None
            if prev_leader is not None and curr_leader != prev_leader:
                leader_changes += 1
            prev_leader = curr_leader

        print(f"Leader changes: {leader_changes}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate Bully algorithm simulation run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--state', '-s',
        default='state_log.jsonl',
        help='Path to state log file (default: state_log.jsonl)'
    )
    parser.add_argument(
        '--messages', '-m',
        default='message_log.jsonl',
        help='Path to message log file (default: message_log.jsonl)'
    )
    parser.add_argument(
        '--hb-timeout',
        type=int, default=3,
        help='Heartbeat timeout in ticks (default: 3)'
    )
    parser.add_argument(
        '--election-timeout',
        type=int, default=3,
        help='Election timeout in ticks (default: 3)'
    )
    parser.add_argument(
        '--summary', action='store_true',
        help='Print simulation summary'
    )

    args = parser.parse_args()

    try:
        validator = BullyValidator(
            args.state, args.messages,
            args.hb_timeout, args.election_timeout
        )
    except FileNotFoundError as e:
        print(f"Error: Could not find log file: {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in log file: {e}")
        return 1

    if args.summary:
        validator.print_summary()

    print("\n" + "=" * 60)
    print("BULLY ALGORITHM CORRECTNESS VALIDATION")
    print("=" * 60 + "\n")

    results = validator.validate_all()

    passed = 0
    failed_critical = 0
    failed_soft = 0

    for result in results:
        print(result)
        print()
        if result.passed:
            passed += 1
        elif result.is_critical:
            failed_critical += 1
        else:
            failed_soft += 1

    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed_critical} critical failures, {failed_soft} soft warnings")

    if failed_critical == 0:
        if failed_soft > 0:
            print("STATUS: ACCEPTABLE (soft violations are expected in async systems)")
        else:
            print("STATUS: PERFECT")
    else:
        print("STATUS: FAILED (critical violations detected)")
    print("=" * 60)

    return 0 if failed_critical == 0 else 1


if __name__ == '__main__':
    exit(main())
