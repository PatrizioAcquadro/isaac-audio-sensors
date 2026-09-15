// Use identical native segment bounds for baking, route validation and capture.
#pragma once
inline bool iasSegmentBlocked(const ipl::IScene& scene,
    const ipl::Vector3f& a, const ipl::Vector3f& b) {
    auto delta = b - a;
    auto length = delta.length();
    if (length <= 1e-7f) return false;
    auto direction = ipl::Vector3f::unitVector(delta);
    constexpr float tolerance = 1e-5f;
    return scene.anyHit(ipl::Ray{a - tolerance * direction, direction},
        0.f, length + 2.f*tolerance);
}
