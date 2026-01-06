#pragma once
#include <cstdint>

enum class MsgType : int32_t {
    HEARTBEAT   = 1,
    ELECTION    = 2,
    OK          = 3,
    COORDINATOR = 4,
    PING        = 5,
    ACK         = 6,
    STATE_REPORT= 7
};

// Fixed-size, trivially serializable message payload.
// We'll send it using MPI_BYTE to keep it simple and portable.
struct Message {
    int32_t type;      // MsgType
    int32_t tick;
    int32_t src_uid;
    int32_t dst_uid;
    int32_t leader_uid; // for COORDINATOR / state
    int32_t aux;        // reserved (e.g., reason codes, msg id)
};

struct StateReport {
    int32_t tick;
    int32_t uid;
    int32_t online;       // 0/1
    int32_t leader_uid;   // -1 unknown
    int32_t election_active; // 0/1
    int32_t last_hb_tick; // -1 if never
};