#pragma once
#include <random>
#include <vector>
#include <cstdint>
#include <memory>

// Seed mixing utility
static inline uint64_t mix_seed(uint64_t base, uint64_t id) {
    uint64_t x = base ^ (id + 0x9e3779b97f4a7c15ULL);
    x ^= x >> 30;
    x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27;
    x *= 0x94d049bb133111ebULL;
    x ^= x >> 31;
    return x;
}

// Abstract base class for failure models
// Extend this to implement different failure semantics
class Failure {
public:
    virtual ~Failure() = default;

    // Called each tick to update failure state
    virtual void tick(int tick) = 0;

    // Whether the node can send/receive messages
    virtual bool can_communicate() const = 0;

    // For logging/visualization
    virtual bool is_failed() const { return !can_communicate(); }
    virtual int ticks_until_recovery() const { return 0; }

    // Human-readable failure type for logs
    virtual const char* type_name() const = 0;
};

// Configuration for network failure model
struct NetworkFailureConfig {
    double p_fail = 0.02;
    double leader_fail_multiplier = 2.0;
    std::vector<int> offline_durations{1, 2, 3, 5};
    std::vector<int> offline_weights{70, 20, 7, 3};
};

// Network failure: node runs but messages don't get through
// Models network partitions, connectivity loss, etc.
class NetworkFailure : public Failure {
public:
    NetworkFailure(int uid, uint64_t base_seed, const NetworkFailureConfig& cfg)
        : uid_(uid)
        , cfg_(cfg)
        , rng_(mix_seed(base_seed, static_cast<uint64_t>(uid)))
        , offline_dist_(cfg.offline_weights.begin(), cfg.offline_weights.end())
    {}

    void tick(int tick) override {
        (void)tick;

        if (offline_remaining_ > 0) {
            offline_remaining_--;
            return;
        }

        double p = is_leader_ ? cfg_.p_fail * cfg_.leader_fail_multiplier 
                              : cfg_.p_fail;

        if (uni_(rng_) < p) {
            int idx = offline_dist_(rng_);
            offline_remaining_ = cfg_.offline_durations[idx];
        }
    }

    bool can_communicate() const override {
        return offline_remaining_ == 0;
    }

    int ticks_until_recovery() const override {
        return offline_remaining_;
    }

    const char* type_name() const override {
        return "NetworkFailure";
    }

    // Call this each tick before tick() if leader status affects failure rate
    void set_is_leader(bool is_leader) {
        is_leader_ = is_leader;
    }

private:
    int uid_;
    NetworkFailureConfig cfg_;
    std::mt19937_64 rng_;
    std::discrete_distribution<int> offline_dist_;
    std::uniform_real_distribution<double> uni_{0.0, 1.0};

    int offline_remaining_ = 0;
    bool is_leader_ = false;
};

// Crash failure: node fully stops (no internal logic runs)
// For future use - provides different semantics than network failure
class CrashFailure : public Failure {
public:
    CrashFailure(int uid, uint64_t base_seed, double p_crash, int recovery_ticks)
        : uid_(uid)
        , p_crash_(p_crash)
        , recovery_ticks_(recovery_ticks)
        , rng_(mix_seed(base_seed, static_cast<uint64_t>(uid)))
    {}

    void tick(int tick) override {
        (void)tick;

        if (crashed_remaining_ > 0) {
            crashed_remaining_--;
            return;
        }

        if (uni_(rng_) < p_crash_) {
            crashed_remaining_ = recovery_ticks_;
        }
    }

    bool can_communicate() const override {
        return crashed_remaining_ == 0;
    }

    // Crash failure also stops internal logic
    bool is_crashed() const {
        return crashed_remaining_ > 0;
    }

    int ticks_until_recovery() const override {
        return crashed_remaining_;
    }

    const char* type_name() const override {
        return "CrashFailure";
    }

private:
    int uid_;
    double p_crash_;
    int recovery_ticks_;
    std::mt19937_64 rng_;
    std::uniform_real_distribution<double> uni_{0.0, 1.0};

    int crashed_remaining_ = 0;
};

// No-op failure model for testing pure algorithm behavior
class NoFailure : public Failure {
public:
    void tick(int tick) override { (void)tick; }
    bool can_communicate() const override { return true; }
    const char* type_name() const override { return "NoFailure"; }
};

// Factory function for creating failure models from config
enum class FailureType {
    None,
    Network,
    Crash
};
 
inline std::unique_ptr<Failure> make_failure(
    FailureType type,
    int uid,
    uint64_t seed,
    const NetworkFailureConfig& net_cfg = {},
    double crash_p = 0.02,
    int crash_recovery = 3
) {
    switch (type) {
        case FailureType::Network:
            return std::make_unique<NetworkFailure>(uid, seed, net_cfg);
        case FailureType::Crash:
            return std::make_unique<CrashFailure>(uid, seed, crash_p, crash_recovery);
        case FailureType::None:
        default:
            return std::make_unique<NoFailure>();
    }
}

