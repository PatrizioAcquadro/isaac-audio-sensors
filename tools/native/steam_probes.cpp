// Native automatic probe preparation and selected-path search. No IAS traversal.
#include "api_scene.h"
#include "path_simulator.h"
#include "probe_generator.h"
#include "steam_visibility_cache.h"
#include <cmath>
#include <memory>
#include <mutex>

namespace {
struct Paths {
    ipl::shared_ptr<ipl::ProbeBatch> probes;
    std::unique_ptr<ipl::ProbeTree> tree;
    std::unique_ptr<ipl::PathSimulator> simulator;
    ipl::vector<unsigned char> visibility;
    float range;
};
// Steam's baker owns process-global state; independent scenes serialize baking.
std::mutex bakeMutex;
bool finite3(const float* v) {
    return v && std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
}
bool neighborhood(Paths& paths, const ipl::IScene& scene, const ipl::Vector3f& point,
    ipl::ProbeNeighborhood& result) {
    // Steam's bounded tree lookup returns traversal order. Query its full native
    // neighborhood before retaining the nearest visible eight interpolation nodes.
    ipl::ProbeNeighborhood candidates;
    candidates.resize(paths.probes->numProbes());
    paths.tree->getInfluencingProbes(point, paths.probes->probes(),
        candidates.numProbes(), candidates.probeIndices.data());
    bool covered = false;
    for (int i = 0; i < candidates.numProbes(); ++i) {
        if (candidates.probeIndices[i] >= 0) {
            candidates.batches[i] = paths.probes.get();
            covered = true;
        }
    }
    candidates.checkOcclusion(scene, point);
    ipl::vector<int> visible;
    for (int i = 0; i < candidates.numProbes(); ++i)
        if (candidates.probeIndices[i] >= 0) visible.push_back(candidates.probeIndices[i]);
    std::sort(visible.begin(), visible.end(), [&](int a, int b) {
        const auto& pa = (*paths.probes)[a].influence.center;
        const auto& pb = (*paths.probes)[b].influence.center;
        auto da = (pa-point).lengthSquared(), db = (pb-point).lengthSquared();
        if (da != db) return da < db;
        for (int axis = 0; axis < 3; ++axis)
            if (pa[axis] != pb[axis]) return pa[axis] < pb[axis];
        return false;
    });
    result.resize(8);
    for (int i = 0; i < 8 && i < int(visible.size()); ++i) {
        result.batches[i] = paths.probes.get();
        result.probeIndices[i] = visible[i];
    }
    return covered;
}
}

extern "C" __attribute__((visibility("default"))) int ias_probes_abi() { return 1; }

extern "C" __attribute__((visibility("default"))) int ias_probes_create(
    void* sceneHandle, const float* bounds, float spacing, float height,
    int maxProbes, void** output) {
    if (!sceneHandle || !output || !finite3(bounds) || !finite3(bounds + 3)
        || !std::isfinite(spacing) || spacing <= 0 || !std::isfinite(height)
        || height <= 0 || maxProbes <= 0) return -1;
    *output = nullptr;
    try {
        auto scene = reinterpret_cast<api::CScene*>(sceneHandle)->mHandle.get();
        if (!scene) return -1;
        ipl::Matrix4x4f transform;
        transform.identity();
        for (int i = 0; i < 3; ++i) {
            if (bounds[i + 3] <= bounds[i]) return -1;
            transform(i,i) = bounds[i + 3] - bounds[i];
            transform(i,3) = .5f * (bounds[i + 3] + bounds[i]);
        }
        // Bound the grid before native allocation; count all generated floors too.
        double cells = (std::floor(transform(0,0)/spacing)+1)
                     * (std::floor(transform(2,2)/spacing)+1);
        if (cells > 16.0 * maxProbes) return -3;
        // Center the native floor lattice within horizontal cells, away from
        // boundary walls and corners. Keep the original bounds for the range.
        auto generationTransform = transform;
        for (int axis : {0, 2})
            generationTransform(axis,axis) = std::max(spacing * .01f,
                transform(axis,axis) - spacing);
        ipl::ProbeArray generated;
        ipl::ProbeGenerator::generateProbes(*scene, generationTransform,
            ipl::ProbeGenerationType::UniformFloor, spacing, height, generated);
        ipl::vector<ipl::Probe> retained;
        for (int i = 0; i < generated.numProbes(); ++i) {
            auto probe = generated[i];
            const auto& center = probe.influence.center;
            bool valid = true;
            for (int axis = 0; axis < 3; ++axis) {
                if (center[axis] < bounds[axis] || center[axis] > bounds[axis+3]) valid = false;
                ipl::Vector3f direction(0.f,0.f,0.f);
                direction[axis] = 1.f;
                // Offset native rays also detect triangle edges/corners; a ray
                // exactly through a vertex can miss both adjoining triangles.
                for (int u = -1; u <= 1; ++u) {
                    for (int v = -1; v <= 1; ++v) {
                        auto origin = center - 1e-4f*direction;
                        origin[(axis+1)%3] += u*5e-5f;
                        origin[(axis+2)%3] += v*5e-5f;
                        if (scene->anyHit(ipl::Ray{origin, direction}, 0.f, 2e-4f)) valid = false;
                    }
                }
            }
            if (valid) {
                probe.influence.radius = std::max(spacing, height);
                retained.push_back(probe);
                if (retained.size() > size_t(maxProbes)) return -3;
            }
        }
        if (retained.empty()) return -2;
        generated.probes.resize(retained.size());
        for (int i = 0; i < generated.numProbes(); ++i) generated[i] = retained[i];
        auto paths = std::make_unique<Paths>();
        paths->range = std::sqrt(transform(0,0)*transform(0,0)
            + transform(1,1)*transform(1,1) + transform(2,2)*transform(2,2));
        paths->probes = ipl::make_shared<ipl::ProbeBatch>();
        paths->probes->addProbeArray(generated);
        paths->probes->commit();
        ipl::BakedDataIdentifier id;
        id.type = ipl::BakedDataType::Pathing;
        id.variation = ipl::BakedDataVariation::Dynamic;
        {
            std::lock_guard<std::mutex> lock(bakeMutex);
            // A bent path can exceed the scene diagonal. A simple graph path
            // has fewer than N edges; do not truncate valid interpolation pairs.
            const auto pathRange = paths->range * generated.numProbes();
            ipl::PathBaker::bake(*scene, id, 1, 0.f, .5f, paths->range,
                paths->range, pathRange, false, -ipl::Vector3f::kYAxis,
                false, 1, *paths->probes, [](float, void*) {});
        }
        if (!paths->probes->hasData(id)) return -4;
        paths->tree = std::make_unique<ipl::ProbeTree>(
            paths->probes->numProbes(), paths->probes->probes());
        paths->simulator = std::make_unique<ipl::PathSimulator>(
            *paths->probes, 1, false, -ipl::Vector3f::kYAxis);
        *output = paths.release();
        return generated.numProbes();
    } catch (...) { return -4; }
}

extern "C" __attribute__((visibility("default"))) void ias_probes_release(void* handle) {
    delete static_cast<Paths*>(handle);
}

extern "C" __attribute__((visibility("default"))) int ias_probes_find(
    void* handle, void* sceneHandle, const float* source, const float* listener) {
    if (!handle || !sceneHandle || !finite3(source) || !finite3(listener)) return -1;
    try {
        auto& paths = *static_cast<Paths*>(handle);
        auto scene = reinterpret_cast<api::CScene*>(sceneHandle)->mHandle.get();
        if (!scene) return -1;
        ipl::Vector3f s(source[0], source[1], source[2]);
        ipl::Vector3f r(listener[0], listener[1], listener[2]);
        if (!scene->isOccluded(s,r)) return 1; // Direct renderer owns LOS.
        ipl::ProbeNeighborhood sp, rp;
        if (!neighborhood(paths,*scene,s,sp)) return -2;
        if (!neighborhood(paths,*scene,r,rp)) return -3;
        if (!sp.hasValidProbes() || !rp.hasValidProbes()) return -4;
        sp.calcWeights(s);
        rp.calcWeights(r);
        // All endpoint pairs use the same immutable scene during this call.
        // Keep ordered edges: reversing a floating-point ray need not be identical.
        const int size = paths.probes->numProbes();
        paths.visibility.assign(size_t(size) * size, 0);
        ipl::iasVisibilityCache = paths.visibility.data();
        ipl::iasVisibilitySize = size;
        struct CacheScope {
            ~CacheScope() { ipl::iasVisibilityCache = nullptr; ipl::iasVisibilitySize = 0; }
        } cacheScope;
        float eq[3], sh[1];
        return paths.simulator->findPaths(s,r,*scene,*paths.probes,sp,rp,
            0.f,.5f,paths.range,0,true,true,true,true,eq,sh,
            ipl::DistanceAttenuationModel(),ipl::DeviationModel()) ? 0 : -4;
    } catch (...) { return -5; }
}
