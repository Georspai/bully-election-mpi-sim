#pragma once
#include <mpi.h>
#include <random>
#include <algorithm>
#include "messages.hpp"
#include "logger.hpp"
#include "failure.hpp"  // For mix_seed utility

struct NodeConfig {
    // Heartbeats
    int hb_period_ticks = 1;
    int hb_timeout_ticks = 3;

    // Election
    int election_timeout_ticks = 3;  // Match hb_timeout_ticks

    // Traffic
    double p_send = 0.30;
    double p_drop = 0.0;

    int max_recv_per_tick = 64;
    uint64_t seed = 0;

    bool debug = true;
};

class Node
{

public:
  Node(int mpi_rank, int world_size, int num_nodes, const NodeConfig &cfg)
      : rank_(mpi_rank),
        world_size_(world_size),
        num_nodes_(num_nodes),
        uid_(mpi_rank), // initial: uid == rank (ranks 1..N are nodes)
        cfg_(cfg),
        rng_(mix_seed(cfg.seed, static_cast<uint64_t>(mpi_rank)))
  {
    if (rank_ == 0)
    {
      throw std::runtime_error("Node should not be constructed for controller rank 0");
    }
    if (world_size_ != num_nodes_ + 1)
    {
      throw std::runtime_error("world_size must equal num_nodes + 1");
    }

    leader_uid_ = num_nodes_;
    last_hb_tick_ = -1;
  }

  void tick_begin(int tick)
  {
    (void)tick;
    // Failure state is now injected externally via set_can_communicate()
  }
  void tick_send(int tick)
  {
    // Algorithm always runs - message filtering happens at transport level
    maybe_send_heartbeat(tick);

    // Election initiation: send ELECTION to all higher-UID nodes
    if (election_active_ && !election_started_)
    {
      start_election(tick);
    }

    // Random background traffic
    maybe_send_random_ping(tick);
  }

  void tick_recv(int tick)
  {
    // Always drain incoming - filtering happens inside drain_incoming
    drain_incoming(tick);
  }

  void tick_end(int tick)
  {
    // Algorithm always runs - failure only affects message transport

    // Failure detection: if heartbeat is too old and not already in election/waiting, start election
    if (leader_uid_ != -1 && uid_ != leader_uid_ && !election_active_ && !waiting_for_coordinator_)
    {
      if (last_hb_tick_ >= 0 && (tick - last_hb_tick_) >= cfg_.hb_timeout_ticks)
      {
        election_active_ = true;
        election_started_ = false;
        debug_print(tick, "⏱ timeout: no heartbeat from leader, starting election");
      }
    }

    // Check if we're waiting for COORDINATOR and it timed out
    if (waiting_for_coordinator_)
    {
      const int elapsed = tick - ok_received_tick_;
      if (elapsed > cfg_.election_timeout_ticks)
      {
        // Higher node failed to send COORDINATOR - restart our own election
        waiting_for_coordinator_ = false;
        ok_received_tick_ = -1;
        election_active_ = true;
        election_started_ = false;
        debug_print(tick, "⏱ timeout: no COORDINATOR received, restarting election");
      }
    }

    // Check if our election attempt timed out (no OK received)
    if (election_active_ && election_started_)
    {
      const int elapsed = tick - election_start_tick_;
      if (elapsed > cfg_.election_timeout_ticks)
      {
        // No higher node responded - we are the new leader
        leader_uid_ = uid_;
        election_active_ = false;
        election_started_ = false;
        debug_print(tick, "👑 won election: becoming leader");

        Message coord{};
        coord.type = static_cast<int32_t>(MsgType::COORDINATOR);
        coord.tick = tick;
        coord.src_uid = uid_;
        coord.dst_uid = -1;
        coord.leader_uid = uid_;
        coord.aux = 0;

        broadcast_to_nodes(coord);
        debug_print(tick, "→ COORDINATOR to all: I am leader");
      }
    }
  }

  // For controller logging (rank 0)
  StateReport make_state_report(int tick) const
  {
    StateReport r;
    r.tick = tick;
    r.uid = uid_;
    r.online = can_communicate_ ? 1 : 0;  // Report communication status
    r.leader_uid = leader_uid_;
    r.election_active = election_active_ ? 1 : 0;
    r.last_hb_tick = last_hb_tick_;
    return r;
  }

  int uid() const { return uid_; }
  bool can_communicate() const { return can_communicate_; }
  void set_can_communicate(bool can) { can_communicate_ = can; }
  int leader_uid() const { return leader_uid_; }
  bool election_active() const { return election_active_; }

  // Message buffer access for logging
  const MessageBuffer& message_buffer() const { return msg_buffer_; }
  MessageBuffer& message_buffer() { return msg_buffer_; }
  void clear_message_buffer() { msg_buffer_.clear(); }

  // Debug message buffer access for logging
  const std::vector<std::string>& debug_messages() const { return debug_messages_; }
  void clear_debug_messages() { debug_messages_.clear(); }

private:
  // MPI / topology
  int rank_;
  int world_size_;
  int num_nodes_; // excludes controller rank 0

  // Identity
  int uid_;

  // Core state
  int leader_uid_ = -1;
  int last_hb_tick_ = -1;

  // Communication state (injected from outside via set_can_communicate)
  bool can_communicate_ = true;

  // Election state
  bool election_active_ = false;
  bool election_started_ = false;  // True if we've sent ELECTION messages this round
  bool waiting_for_coordinator_ = false;  // True after receiving OK, waiting for COORDINATOR
  int ok_received_tick_ = -1;  // Tick when we received OK (for COORDINATOR timeout)
  int election_start_tick_ = -1;

  NodeConfig cfg_;

  // RNG
  std::mt19937_64 rng_;
  std::uniform_real_distribution<double> uni_{0.0, 1.0};

  // Message buffer for logging
  MessageBuffer msg_buffer_;

  // Debug message buffer for logging
  std::vector<std::string> debug_messages_;

private:
  int32_t next_msg_id = 0;
  int32_t pings_sent = 0;
  int32_t acks_received = 0;

  bool is_controller() const { return rank_ == 0; }
  bool is_node() const { return rank_ > 0; }

  bool is_leader() const { return uid_ == leader_uid_; }

  // Internal helpers
  void maybe_send_heartbeat(int tick)
  {
    // Only leader sends heartbeat
    if (uid_ != leader_uid_)
      return;

    if (cfg_.hb_period_ticks <= 0)
      return;
    if (tick % cfg_.hb_period_ticks != 0)
      return;
    debug_print(tick, "→ HEARTBEAT to all");
    Message m{};
    m.type = static_cast<int32_t>(MsgType::HEARTBEAT);
    m.tick = tick;
    m.src_uid = uid_;
    m.dst_uid = -1; // broadcast
    m.leader_uid = uid_;
    m.aux = 0;

    broadcast_to_nodes(m);
  }

  void start_election(int tick)
  {
    election_started_ = true;
    election_start_tick_ = tick;

    // Send ELECTION to all nodes with higher UID
    Message m{};
    m.type = static_cast<int32_t>(MsgType::ELECTION);
    m.tick = tick;
    m.src_uid = uid_;
    m.dst_uid = -1;
    m.leader_uid = leader_uid_;
    m.aux = 0;

    bool sent_any = false;
    for (int r = 1; r <= num_nodes_; ++r)
    {
      if (r > uid_)  // r is the UID (since uid == rank for nodes)
      {
        bool dropped = should_drop_outgoing();
        send_message(m, r, dropped);
        if (!dropped) {
          sent_any = true;
          debug_print(tick, "→ ELECTION to " + std::to_string(r));
        } else {
          debug_print(tick, "✗ ELECTION to " + std::to_string(r) + " (dropped)");
        }
      }
    }

    if (!sent_any && uid_ == num_nodes_)
    {
      // We are the highest UID node - no one to send to, we win immediately
      debug_print(tick, "👑 no higher nodes: winning immediately");
    }
  }

  void handle_message(const Message &m, int tick)
  {
    const auto type = static_cast<MsgType>(m.type);

    switch (type)
    {
    case MsgType::HEARTBEAT:
      if (m.src_uid >= uid_) {  // Accept from any valid leader candidate
        leader_uid_ = m.src_uid;
        last_hb_tick_ = tick;
        election_active_ = false;  // Cancel any ongoing election
        waiting_for_coordinator_ = false;
        debug_print(tick, "← HEARTBEAT from " + std::to_string(m.src_uid));
      }
      break;
    case MsgType::ELECTION:
      // Respond with OK to the sender
      {
        Message ok{};
        ok.type = static_cast<int32_t>(MsgType::OK);
        ok.tick = tick;
        ok.src_uid = uid_;
        ok.dst_uid = m.src_uid;
        ok.leader_uid = leader_uid_;
        ok.aux = 0;

        bool dropped = should_drop_outgoing();
        send_message(ok, m.src_uid, dropped);
        if (!dropped) {
          debug_print(tick, "→ OK to " + std::to_string(m.src_uid));
        } else {
          debug_print(tick, "✗ OK to " + std::to_string(m.src_uid) + " (dropped)");
        }

        // If sender has lower UID than us, start our own election
        if (m.src_uid < uid_ && !election_active_)
        {
          election_active_ = true;
          election_started_ = false;
          debug_print(tick, "← ELECTION from " + std::to_string(m.src_uid) + ": starting own election");
        }
      }
      break;

    case MsgType::OK:
      // A higher node is alive - stop our election and wait for their COORDINATOR
      // Only accept OK from nodes with higher UID than us
      if (m.src_uid > uid_) {
        election_active_ = false;
        election_started_ = false;
        waiting_for_coordinator_ = true;
        ok_received_tick_ = tick;
        debug_print(tick, "← OK from " + std::to_string(m.src_uid) + ": yielding, waiting for COORDINATOR");
      }
      break;

    case MsgType::COORDINATOR:
      if (m.src_uid >= uid_)
      {
        // Accept COORDINATOR from equal or higher priority node
        debug_print(tick, "← COORDINATOR from " + std::to_string(m.src_uid) + ": accepted as leader");
        leader_uid_ = m.src_uid;
        last_hb_tick_ = tick;
        election_active_ = false;
        election_started_ = false;
        waiting_for_coordinator_ = false;
        ok_received_tick_ = -1;
      }
      else
      {
        // Reject COORDINATOR from lower priority node - start election
        debug_print(tick, "← COORDINATOR from " + std::to_string(m.src_uid) + ": rejected (lower UID), starting election");
        if (!election_active_ && !waiting_for_coordinator_)
        {
          election_active_ = true;
          election_started_ = false;
        }
      }
      break;
    case MsgType::PING:
    {
      Message ack{};
      ack.type = static_cast<int32_t>(MsgType::ACK);
      ack.tick = tick;
      ack.dst_uid = m.src_uid;
      ack.src_uid = uid_;
      ack.leader_uid = leader_uid_;
      ack.aux = m.aux;

      bool dropped = should_drop_outgoing();
      send_message(ack, ack.dst_uid, dropped);
      if (!dropped) {
        debug_print(tick, "→ ACK to " + std::to_string(ack.dst_uid));
      } else {
        debug_print(tick, "✗ ACK to " + std::to_string(ack.dst_uid) + " (dropped)");
      }
      break;
    }
  default:
    // For now ignore others
    break;
  }
}

inline bool
should_drop_outgoing()
{
  if (cfg_.p_drop <= 0.0)
    return false;

  return uni_(rng_) <= cfg_.p_drop;
}

int random_peer_rank()
{
  std::uniform_int_distribution<int> dist(1, num_nodes_);

  int r = rank_;
  while (r == rank_)
  {
    r = dist(rng_);
  }

  return r;
}

void maybe_send_random_ping(int tick)
{
  // Algorithm always runs - message filtering happens at transport level
  if (cfg_.p_send <= 0.0)
    return;
  if (uni_(rng_) >= cfg_.p_send)
    return;

  const int destination_node = random_peer_rank();

  Message m{};
  m.type = static_cast<int32_t>(MsgType::PING);
  m.tick = tick;
  m.src_uid = uid_;
  m.dst_uid = destination_node;
  m.leader_uid = leader_uid_;
  m.aux = next_msg_id++;

  bool dropped = should_drop_outgoing();
  send_message(m, destination_node, dropped);
  if (!dropped) {
    ++pings_sent;
    debug_print(tick, "→ PING to " + std::to_string(destination_node));
  } else {
    debug_print(tick, "✗ PING to " + std::to_string(m.dst_uid) + " (dropped)");
  }
}

// MPI send helpers (simple; we'll refine later)
void send_message(const Message &m, int dst_rank, bool dropped = false)
{
  // Transport-level filtering: if we can't communicate, message is silently dropped
  bool effectively_dropped = dropped || !can_communicate_;

  // Log the send event (mark as dropped if we can't communicate)
  msg_buffer_.log_send(m.tick, m, dst_rank, effectively_dropped);

  if (!effectively_dropped) {
    MPI_Send(
        &m,
        static_cast<int>(sizeof(Message)),
        MPI_BYTE,
        dst_rank,
        /*tag*/ 100,
        MPI_COMM_WORLD);
  }
}

void broadcast_to_nodes(const Message &m)
{
  for (int r = 1; r <= num_nodes_; ++r)
  {
    if (r == rank_)
      continue;
    send_message(m, r);
  }
}

// Receive helper
void drain_incoming(int tick)
{
  int drained = 0;

  while (drained < cfg_.max_recv_per_tick)
  {
    MPI_Status status;
    int flag = 0;

    MPI_Iprobe(MPI_ANY_SOURCE, 100, MPI_COMM_WORLD, &flag, &status);
    if (!flag)
      break;

    Message m{};
    MPI_Recv(&m, static_cast<int>(sizeof(Message)), MPI_BYTE,
             status.MPI_SOURCE, 100, MPI_COMM_WORLD, MPI_STATUS_IGNORE);

    // Log the receive event (even if can't communicate - shows what was missed)
    msg_buffer_.log_recv(tick, m);

    // Transport-level filtering: if we can't communicate, message is ignored
    if (can_communicate_)
    {
      handle_message(m, tick);
      // Note: specific handlers already log received messages with context
    }

    drained++;
  }
}



void debug_print(int tick, const std::string &msg)
{
  // Always store for logging (even if debug output is disabled)
  debug_messages_.push_back(msg);

  if (!cfg_.debug)
    return;

  std::ostringstream oss;
  oss << "[T=" << tick << "][R=" << uid_ << "] " << msg << "\n";
  std::cout << oss.str();
}
}
;
