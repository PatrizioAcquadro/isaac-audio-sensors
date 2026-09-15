// Pre-histogram PRA transport capture. Geometry and ray traversal stay in PRA.
#pragma once
#include <cstdint>
#include <stdexcept>
#include <vector>

struct IASPraEvent {
    std::uint64_t ray;
    std::int64_t parent;
    int kind, surface, receiver, bounce, diffuse_bounces, scattered;
    float distance, position[3], incoming[3], departure[3], local[2];
};

namespace ias_pra {
struct Capture {
    std::uint64_t seed = 0, ray = 0;
    std::int64_t parent = -1;
    int bounce = 0, diffuse_bounces = 0;
    std::size_t limit = 0;
    float departure[3]{};
    std::vector<IASPraEvent> events;
    std::vector<float> energies;

    template<class P> void begin(const P& direction) {
        ++ray;
        parent = -1;
        bounce = diffuse_bounces = 0;
        for (int k = 0; k < 3; ++k) departure[k] = direction[k];
        rng::set_seed(seed ^ (ray * UINT64_C(0x9e3779b97f4a7c15)));
    }

    template<class P, class E, class W>
    void surface(int id, const W& wall, const P& point, const P& direction,
                 float distance, const E& energy) {
        append(0, id, -1, point, direction, distance, energy);
        auto uv = (wall.basis.transpose() * (point - wall.origin)).eval();
        events.back().local[0] = uv[0];
        events.back().local[1] = uv[1];
        parent = static_cast<std::int64_t>(events.size()) - 1;
        ++bounce;
    }

    template<class P, class E>
    void append(int kind, int surface, int receiver, const P& point,
                const P& direction, float distance, const E& energy) {
        if (events.size() >= limit)
            throw std::runtime_error("PRA event budget exceeded; capture is incomplete.");
        IASPraEvent event{};
        event.ray = ray;
        event.parent = parent;
        event.kind = kind;
        event.surface = surface;
        event.receiver = receiver;
        event.bounce = bounce;
        event.diffuse_bounces = diffuse_bounces;
        event.distance = distance;
        for (int k = 0; k < 3; ++k) {
            event.position[k] = point[k];
            event.incoming[k] = direction[k];
            event.departure[k] = departure[k];
        }
        events.push_back(event);
        for (int b = 0; b < energy.size(); ++b) energies.push_back(energy[b]);
    }

    void branch(bool scattered) {
        events.at(static_cast<std::size_t>(parent)).scattered = scattered;
        diffuse_bounces += scattered;
    }
};
inline thread_local Capture* capture = nullptr;
}
