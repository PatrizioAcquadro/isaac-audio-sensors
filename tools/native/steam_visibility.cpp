// Private queries for time-indexed Steam 4.8.1 geometry; no custom ray traversal.
#include "api_scene.h"
#include <cmath>

extern "C" __attribute__((visibility("default"))) int ias_visibility_abi() { return 1; }

extern "C" __attribute__((visibility("default"))) int ias_scene_segments(
    void* handle, int count, const float* starts, const float* ends, unsigned char* blocked) {
    if (!handle || count < 0 || !starts || !ends || !blocked) return -1;
    auto scene = reinterpret_cast<api::CScene*>(handle)->mHandle.get();
    if (!scene) return -1;
    for (int i = 0; i < count; ++i) {
        for (int j = 0; j < 3; ++j)
            if (!std::isfinite(starts[3*i+j]) || !std::isfinite(ends[3*i+j])) return -1;
        ipl::Vector3f a(starts[3*i], starts[3*i+1], starts[3*i+2]);
        ipl::Vector3f b(ends[3*i], ends[3*i+1], ends[3*i+2]);
        auto length = (b-a).length();
        if (length <= 1e-7f) { blocked[i] = 0; continue; }
        // Embree excludes a hit exactly at the origin. Include the epoch start
        // within 10 micrometres (0.00047 samples at 16 kHz), excluding its end.
        constexpr float startTolerance = 1e-5f;
        auto direction = ipl::Vector3f::unitVector(b-a);
        blocked[i] = scene->anyHit(
            ipl::Ray{a - startTolerance * direction, direction}, 0.f,
            std::nextafter(length + startTolerance, 0.f));
    }
    return 0;
}
