#pragma once
#include <fstream>
#include <vector>
#include <string>
#include <cstdint>
#include <nlohmann/json.hpp>
#include "messages.hpp"

using json = nlohmann::json;

// Maximum messages a node can buffer per tick for logging
constexpr int MAX_MSG_EVENTS_PER_TICK = 32;

// Event logged when a message is sent or received
struct MessageEvent {
    int32_t tick;
    int32_t type;       // MsgType
    int32_t src_uid;
    int32_t dst_uid;    // -1 for broadcast
    int32_t dropped;    // 0 = delivered, 1 = dropped
    int32_t direction;  // 0 = sent, 1 = received
    int32_t padding[2]; // Ensure 32-byte alignment
};

// Helper to convert MsgType to string
inline const char* msg_type_to_string(int32_t type) {
    switch (static_cast<MsgType>(type)) {
        case MsgType::HEARTBEAT:    return "HEARTBEAT";
        case MsgType::ELECTION:     return "ELECTION";
        case MsgType::OK:           return "OK";
        case MsgType::COORDINATOR:  return "COORDINATOR";
        case MsgType::PING:         return "PING";
        case MsgType::ACK:          return "ACK";
        case MsgType::STATE_REPORT: return "STATE_REPORT";
        default:                    return "UNKNOWN";
    }
}

// Debug message entry for logging
struct DebugEntry {
    int32_t tick;
    int32_t uid;
    std::string message;
};

// Logger class for controller (rank 0)
// Writes JSON Lines format for easy parsing
class Logger {
public:
    Logger() = default;

    bool open(const std::string& state_path, const std::string& msg_path,
              const std::string& debug_path = "") {
        state_file_.open(state_path);
        msg_file_.open(msg_path);
        if (!debug_path.empty()) {
            debug_file_.open(debug_path);
        }
        return state_file_.is_open() && msg_file_.is_open();
    }

    void close() {
        if (state_file_.is_open()) state_file_.close();
        if (msg_file_.is_open()) msg_file_.close();
        if (debug_file_.is_open()) debug_file_.close();
    }

    // Write state for all nodes at a given tick
    // Format: {"tick":0,"nodes":[{"uid":1,"online":true,"leader":5,"election":false,"last_hb":0},...]}\n
    void log_states(int tick, const std::vector<StateReport>& reports) {
        if (!state_file_.is_open()) return;

        json j;
        j["tick"] = tick;
        j["nodes"] = json::array();

        for (const auto& r : reports) {
            j["nodes"].push_back({
                {"uid", r.uid},
                {"online", static_cast<bool>(r.online)},
                {"leader", r.leader_uid},
                {"election", static_cast<bool>(r.election_active)},
                {"last_hb", r.last_hb_tick}
            });
        }

        state_file_ << j.dump() << "\n";
        state_file_.flush();
    }

    // Write message events for a tick
    // Format: {"tick":5,"type":"ELECTION","src":3,"dst":5,"dropped":false,"dir":"send"}\n
    void log_messages(const std::vector<MessageEvent>& events) {
        if (!msg_file_.is_open()) return;

        for (const auto& e : events) {
            json j = {
                {"tick", e.tick},
                {"type", msg_type_to_string(e.type)},
                {"src", e.src_uid},
                {"dst", e.dst_uid},
                {"dropped", static_cast<bool>(e.dropped)},
                {"dir", e.direction == 0 ? "send" : "recv"}
            };
            msg_file_ << j.dump() << "\n";
        }
        msg_file_.flush();
    }

    // Write simulation metadata at start
    void log_metadata(int num_nodes, int num_ticks, uint64_t seed) {
        if (!state_file_.is_open()) return;

        json j = {
            {"metadata", true},
            {"num_nodes", num_nodes},
            {"num_ticks", num_ticks},
            {"seed", seed}
        };
        state_file_ << j.dump() << "\n";
        state_file_.flush();
    }

    // Write debug messages for a tick
    // Format: {"tick":14,"uid":4,"msg":"GOING ONLINE (recovered) - passive, waiting for heartbeats"}\n
    void log_debug(const std::vector<DebugEntry>& entries) {
        if (!debug_file_.is_open()) return;

        for (const auto& e : entries) {
            json j = {
                {"tick", e.tick},
                {"uid", e.uid},
                {"msg", e.message}
            };
            debug_file_ << j.dump() << "\n";
        }
        debug_file_.flush();
    }

private:
    std::ofstream state_file_;
    std::ofstream msg_file_;
    std::ofstream debug_file_;
};

// Message buffer for nodes to collect events during a tick
// Will be gathered by controller at end of tick
class MessageBuffer {
public:
    MessageBuffer() : count_(0) {}

    void clear() {
        count_ = 0;
    }

    void add_event(int tick, MsgType type, int src_uid, int dst_uid,
                   bool dropped, bool is_recv) {
        if (count_ >= MAX_MSG_EVENTS_PER_TICK) return;

        events_[count_].tick = tick;
        events_[count_].type = static_cast<int32_t>(type);
        events_[count_].src_uid = src_uid;
        events_[count_].dst_uid = dst_uid;
        events_[count_].dropped = dropped ? 1 : 0;
        events_[count_].direction = is_recv ? 1 : 0;
        events_[count_].padding[0] = 0;
        events_[count_].padding[1] = 0;
        count_++;
    }

    void log_send(int tick, const Message& m, int dst_uid, bool dropped) {
        add_event(tick, static_cast<MsgType>(m.type), m.src_uid, dst_uid, dropped, false);
    }

    void log_recv(int tick, const Message& m) {
        add_event(tick, static_cast<MsgType>(m.type), m.src_uid, m.dst_uid, false, true);
    }

    int count() const { return count_; }
    const MessageEvent* data() const { return events_; }
    MessageEvent* data() { return events_; }

private:
    MessageEvent events_[MAX_MSG_EVENTS_PER_TICK];
    int count_;
};
