#include <mpi.h>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>
#include <numeric>
#include <nlohmann/json.hpp>
#include "node.hpp"
#include "logger.hpp"
#include "failure.hpp"

using json = nlohmann::json;

static std::string parse_string(int argc, char** argv, const std::string& key, const std::string& def) {
    for (int i = 1; i < argc; ++i) {
        if (key == argv[i] && i + 1 < argc) return argv[i + 1];
    }
    return def;
}

struct SimConfig {
    int num_ticks = 50;
    uint64_t seed = 12345;
    NodeConfig node;
    NetworkFailureConfig failure;
    FailureType failure_type = FailureType::Network;
    std::string state_log_file = "state_log.jsonl";
    std::string message_log_file = "message_log.jsonl";
    std::string debug_log_file = "debug_log.jsonl";
    bool verbose = true;
};

SimConfig load_config(const std::string& path) {
    SimConfig config;

    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "Warning: Could not open config file '" << path << "', using defaults\n";
        return config;
    }

    try {
        json j = json::parse(file);

        // Simulation settings
        if (j.contains("simulation")) {
            auto& sim = j["simulation"];
            if (sim.contains("num_ticks")) config.num_ticks = sim["num_ticks"];
            if (sim.contains("seed")) config.seed = sim["seed"];
        }

        // Node settings (algorithm parameters only)
        if (j.contains("node")) {
            auto& node = j["node"];
            if (node.contains("hb_period_ticks")) config.node.hb_period_ticks = node["hb_period_ticks"];
            if (node.contains("hb_timeout_ticks")) config.node.hb_timeout_ticks = node["hb_timeout_ticks"];
            if (node.contains("election_timeout_ticks")) config.node.election_timeout_ticks = node["election_timeout_ticks"];
            if (node.contains("p_send")) config.node.p_send = node["p_send"];
            if (node.contains("p_drop")) config.node.p_drop = node["p_drop"];
            if (node.contains("max_recv_per_tick")) config.node.max_recv_per_tick = node["max_recv_per_tick"];
        }

        // Failure model settings (moved from node to separate config)
        if (j.contains("failure")) {
            auto& fail = j["failure"];
            if (fail.contains("p_fail")) config.failure.p_fail = fail["p_fail"];
            if (fail.contains("leader_fail_multiplier")) config.failure.leader_fail_multiplier = fail["leader_fail_multiplier"];
            if (fail.contains("offline_durations")) config.failure.offline_durations = fail["offline_durations"].get<std::vector<int>>();
            if (fail.contains("offline_weights")) config.failure.offline_weights = fail["offline_weights"].get<std::vector<int>>();
            if (fail.contains("type")) {
                std::string type = fail["type"];
                if (type == "none") config.failure_type = FailureType::None;
                else if (type == "network") config.failure_type = FailureType::Network;
                else if (type == "crash") config.failure_type = FailureType::Crash;
            }
        }
        // Backwards compatibility: also read failure params from node section
        else if (j.contains("node")) {
            auto& node = j["node"];
            if (node.contains("p_fail")) config.failure.p_fail = node["p_fail"];
            if (node.contains("leader_fail_multiplier")) config.failure.leader_fail_multiplier = node["leader_fail_multiplier"];
            if (node.contains("offline_durations")) config.failure.offline_durations = node["offline_durations"].get<std::vector<int>>();
            if (node.contains("offline_weights")) config.failure.offline_weights = node["offline_weights"].get<std::vector<int>>();
        }

        // Logging settings
        if (j.contains("logging")) {
            auto& log = j["logging"];
            if (log.contains("state_log_file")) config.state_log_file = log["state_log_file"];
            if (log.contains("message_log_file")) config.message_log_file = log["message_log_file"];
            if (log.contains("debug_log_file")) config.debug_log_file = log["debug_log_file"];
            if (log.contains("verbose")) config.verbose = log["verbose"];
        }

        // Apply seed to node config
        config.node.seed = config.seed;
        config.node.debug = config.verbose;

    } catch (const json::exception& e) {
        std::cerr << "Error parsing config file: " << e.what() << "\n";
    }

    return config;
}

struct MpiEnv
{
  MpiEnv(int &argc, char **&argv)
  {
    int rc = MPI_Init(&argc, &argv);
    if (rc != MPI_SUCCESS)
      std::abort();
  }
  ~MpiEnv() { MPI_Finalize(); }
  MpiEnv(const MpiEnv &) = delete;
  MpiEnv &operator=(const MpiEnv &) = delete;
};

struct MpiInfo
{
  int rank = -1;
  int size = -1;
};

inline MpiInfo mpi_world_info()
{
  MpiInfo info{};
  MPI_Comm_rank(MPI_COMM_WORLD, &info.rank);
  MPI_Comm_size(MPI_COMM_WORLD, &info.size);
  return info;
}

static inline bool is_root(int rank, int root = 0) { return rank == root; }

inline void root_print(int rank, const std::string &msg, int root = 0)
{
  if (rank == root)
    std::cout << msg << std::flush;
}

inline std::string rank_prefix(int rank, int size)
{
  std::ostringstream oss;
  oss << "[rank " << rank << "/" << size << "] ";
  return oss.str();
}

int main(int argc, char **argv)
{
  MpiEnv env(argc, argv);
  const auto [rank, world_size] = mpi_world_info();

  // Load configuration
  std::string config_path = parse_string(argc, argv, "-config", "config.json");
  SimConfig sim_config = load_config(config_path);

  const int ticks = sim_config.num_ticks;
  NodeConfig cfg = sim_config.node;

  // Validate timing constraints for correct Bully algorithm behavior
  // Election timeout must allow for round-trip message delivery:
  // Tick N: send ELECTION, Tick N+1: receive & send OK, Tick N+2: receive OK
  if (cfg.election_timeout_ticks < 3)
  {
    if (rank == 0)
    {
      std::cerr << "Warning: election_timeout_ticks (" << cfg.election_timeout_ticks
                << ") is less than 3. This may cause incorrect election results.\n";
      std::cerr << "Recommended: election_timeout_ticks >= 3 for correct Bully algorithm.\n";
    }
  }

  root_print(rank, "Starting Bully Algorithm Simulation\n");

  // Create a communicator for worker nodes only (excludes rank 0)
  MPI_Comm worker_comm = MPI_COMM_NULL;
  int color = (rank == 0) ? MPI_UNDEFINED : 1;
  MPI_Comm_split(MPI_COMM_WORLD, color, rank, &worker_comm);

  const auto nodes = world_size - 1;

  // Logger for controller
  Logger logger;

  if (rank == 0)
  {
    std::cout << "[Controller] nodes=" << nodes << " ticks=" << ticks
              << " config=" << config_path << "\n";

    // Open log files
    if (!logger.open(sim_config.state_log_file, sim_config.message_log_file,
                     sim_config.debug_log_file)) {
      std::cerr << "[Controller] Failed to open log files\n";
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
    logger.log_metadata(nodes, ticks, sim_config.seed);

    // Controller simulation loop
    for (int t = 0; t < ticks; ++t)
    {
      // Receive state reports from all ranks via MPI_Gather
      // Note: world_size includes rank 0, so we allocate for all ranks
      std::vector<StateReport> all_states_raw(world_size);
      StateReport dummy{}; // Controller doesn't have a state

      MPI_Gather(&dummy, sizeof(StateReport), MPI_BYTE,
                 all_states_raw.data(), sizeof(StateReport), MPI_BYTE,
                 0, MPI_COMM_WORLD);

      // Extract only node states (skip rank 0's dummy data)
      std::vector<StateReport> all_states(all_states_raw.begin() + 1, all_states_raw.end());

      // Receive message event counts from all ranks
      std::vector<int> msg_counts_raw(world_size);
      int dummy_count = 0;

      MPI_Gather(&dummy_count, 1, MPI_INT,
                 msg_counts_raw.data(), 1, MPI_INT,
                 0, MPI_COMM_WORLD);

      // Calculate displacements for MPI_Gatherv (includes all ranks)
      std::vector<int> displs(world_size);
      std::vector<int> byte_counts(world_size);
      int total_msgs = 0;

      for (int i = 0; i < world_size; ++i) {
        displs[i] = total_msgs * static_cast<int>(sizeof(MessageEvent));
        byte_counts[i] = msg_counts_raw[i] * static_cast<int>(sizeof(MessageEvent));
        total_msgs += msg_counts_raw[i];
      }

      // Gather all message events
      std::vector<MessageEvent> all_msgs(total_msgs > 0 ? total_msgs : 1);
      MessageEvent dummy_event{};

      MPI_Gatherv(&dummy_event, 0, MPI_BYTE,
                  all_msgs.data(), byte_counts.data(), displs.data(), MPI_BYTE,
                  0, MPI_COMM_WORLD);

      // Resize to actual count (in case we allocated 1 for empty case)
      if (total_msgs == 0) all_msgs.clear();

      // Gather debug messages from all ranks
      // Each node sends: count of messages, then for each: length + string data
      std::vector<int> debug_counts_raw(world_size);
      int dummy_debug_count = 0;

      MPI_Gather(&dummy_debug_count, 1, MPI_INT,
                 debug_counts_raw.data(), 1, MPI_INT,
                 0, MPI_COMM_WORLD);

      // Gather serialized debug strings (each node serializes all its messages as JSON array)
      std::vector<int> debug_str_lens_raw(world_size);
      int dummy_str_len = 0;

      MPI_Gather(&dummy_str_len, 1, MPI_INT,
                 debug_str_lens_raw.data(), 1, MPI_INT,
                 0, MPI_COMM_WORLD);

      // Calculate displacements for string data
      std::vector<int> debug_displs(world_size);
      int total_debug_bytes = 0;
      for (int i = 0; i < world_size; ++i) {
        debug_displs[i] = total_debug_bytes;
        total_debug_bytes += debug_str_lens_raw[i];
      }

      // Gather all debug string data
      std::vector<char> debug_data(total_debug_bytes > 0 ? total_debug_bytes : 1);
      char dummy_char = '\0';

      MPI_Gatherv(&dummy_char, 0, MPI_BYTE,
                  debug_data.data(), debug_str_lens_raw.data(), debug_displs.data(), MPI_BYTE,
                  0, MPI_COMM_WORLD);

      // Parse debug messages and log them
      std::vector<DebugEntry> all_debug;
      for (int i = 1; i < world_size; ++i) {  // Skip rank 0
        if (debug_str_lens_raw[i] > 0) {
          std::string json_str(debug_data.data() + debug_displs[i], debug_str_lens_raw[i]);
          try {
            json j = json::parse(json_str);
            for (const auto& msg : j) {
              DebugEntry entry;
              entry.tick = t;
              entry.uid = i;  // rank == uid for nodes
              entry.message = msg.get<std::string>();
              all_debug.push_back(entry);
            }
          } catch (...) {
            // Ignore parse errors
          }
        }
      }

      // Log everything
      logger.log_states(t, all_states);
      logger.log_messages(all_msgs);
      logger.log_debug(all_debug);

      // Sync point with workers
      MPI_Barrier(MPI_COMM_WORLD);
    }

    logger.close();
    std::cout << "[Controller] Simulation complete. Logs written to "
              << sim_config.state_log_file << " and " << sim_config.message_log_file << "\n";
  }
  else
  {
    Node node(rank, world_size, nodes, cfg);

    // Create failure model for this node
    auto failure = make_failure(
        sim_config.failure_type,
        rank,  // uid == rank for nodes
        sim_config.seed,
        sim_config.failure);

    for (int t = 0; t < ticks; ++t)
    {
      MPI_Barrier(worker_comm);

      // Update failure state for this tick
      if (auto* net_fail = dynamic_cast<NetworkFailure*>(failure.get())) {
        net_fail->set_is_leader(node.leader_uid() == node.uid());
      }
      failure->tick(t);

      // Inject communication status into node
      node.set_can_communicate(failure->can_communicate());

      node.tick_begin(t);
      node.tick_send(t);
      node.tick_recv(t);
      node.tick_end(t);

      MPI_Barrier(worker_comm);

      // Send state report to controller
      StateReport report = node.make_state_report(t);
      MPI_Gather(&report, sizeof(StateReport), MPI_BYTE,
                 nullptr, 0, MPI_BYTE,
                 0, MPI_COMM_WORLD);

      // Send message event count
      int msg_count = node.message_buffer().count();
      MPI_Gather(&msg_count, 1, MPI_INT,
                 nullptr, 0, MPI_INT,
                 0, MPI_COMM_WORLD);

      // Send message events via Gatherv
      MPI_Gatherv(node.message_buffer().data(),
                  msg_count * static_cast<int>(sizeof(MessageEvent)), MPI_BYTE,
                  nullptr, nullptr, nullptr, MPI_BYTE,
                  0, MPI_COMM_WORLD);

      // Send debug message count
      int debug_count = static_cast<int>(node.debug_messages().size());
      MPI_Gather(&debug_count, 1, MPI_INT,
                 nullptr, 0, MPI_INT,
                 0, MPI_COMM_WORLD);

      // Serialize debug messages as JSON array
      std::string debug_json;
      if (!node.debug_messages().empty()) {
        json j = node.debug_messages();
        debug_json = j.dump();
      }
      int debug_str_len = static_cast<int>(debug_json.size());

      // Send debug string length
      MPI_Gather(&debug_str_len, 1, MPI_INT,
                 nullptr, 0, MPI_INT,
                 0, MPI_COMM_WORLD);

      // Send debug string data
      MPI_Gatherv(debug_json.data(), debug_str_len, MPI_BYTE,
                  nullptr, nullptr, nullptr, MPI_BYTE,
                  0, MPI_COMM_WORLD);

      // Clear buffers for next tick
      node.clear_message_buffer();
      node.clear_debug_messages();

      // Sync with controller
      MPI_Barrier(MPI_COMM_WORLD);
    }
  }

  if (worker_comm != MPI_COMM_NULL)
    MPI_Comm_free(&worker_comm);

  return 0;
}