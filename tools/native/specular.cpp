// C ABI for the qualified Pyroomacoustics image-source engine. No DSP or ray solver here.
#include <algorithm>
#include <memory>
#include <numeric>
#include <string>
#include "common.hpp"
#include "geometry.hpp"
#include "microphone.hpp"
#include "room.hpp"

float libroom_eps = 1e-5f;
namespace {
thread_local std::string error;
struct Scene {
    std::unique_ptr<Room<3>> room;
    int count = 0;
};
}
extern "C" {
int ias_specular_abi() { return 1; }
const char* ias_specular_error() { return error.c_str(); }
void* ias_specular_create(int faces, const int* counts, const float* vertices,
                          int bands, const float* absorption, const float* scattering,
                          int order, float speed) {
    try {
        std::vector<Wall<3>> walls;
        size_t offset = 0;
        for (int i = 0; i < faces; ++i) {
            MatrixXf points(3, counts[i]);
            for (int j = 0; j < counts[i]; ++j)
                for (int k = 0; k < 3; ++k) points(k,j) = vertices[offset++];
            Eigen::ArrayXf a(bands), s(bands);
            for (int b = 0; b < bands; ++b) {
                a[b] = absorption[i*bands+b]; s[b] = scattering[i*bands+b];
            }
            walls.emplace_back(points, a, s, std::to_string(i)+"a");
            // USD surfaces obstruct from either side. Native ISM selects the reflecting side.
            walls.emplace_back(points.rowwise().reverse().eval(), a, s, std::to_string(i)+"b");
        }
        std::vector<int> obstructing(walls.size());
        std::iota(obstructing.begin(), obstructing.end(), 0);
        auto scene = std::make_unique<Scene>();
        scene->room = std::make_unique<Room<3>>(walls, obstructing,
            std::vector<Microphone<3>>{}, speed, order, 1e-7f, 1.f, .1f, .004f, true);
        return scene.release();
    } catch (const std::exception& e) { error = e.what(); return nullptr; }
}
void ias_specular_destroy(void* handle) { delete static_cast<Scene*>(handle); }
int ias_specular_solve(void* handle, const float* source, int microphones, const float* positions) {
    try {
        auto& scene = *static_cast<Scene*>(handle);
        scene.room->microphones.clear();
        for (int i=0; i<microphones; ++i)
            scene.room->add_mic(Vectorf<3>(positions[3*i],positions[3*i+1],positions[3*i+2]));
        scene.count = scene.room->image_source_model(Vectorf<3>(source[0],source[1],source[2]));
        return scene.count;
    } catch (const std::exception& e) { error = e.what(); return -1; }
}
void ias_specular_outputs(void* handle, float* images, float* damping, float* directions,
                          int* orders, unsigned char* visible) {
    const auto& scene = *static_cast<Scene*>(handle);
    if (!scene.count) return;
    const auto& r = *scene.room;
    std::copy_n(r.sources.data(), r.sources.size(), images);
    std::copy_n(r.attenuations.data(), r.attenuations.size(), damping);
    std::copy_n(r.source_directions.data(), r.source_directions.size(), directions);
    std::copy_n(r.orders.data(), scene.count, orders);
    for (int m=0; m<r.microphones.size(); ++m)
        for (int i=0; i<scene.count; ++i) visible[m*scene.count+i]=r.visible_mics(m,i);
}
}
