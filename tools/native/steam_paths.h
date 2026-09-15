// Private selected-route interface for the patched Steam Audio 4.8.1 build.
// Linux C ABI; not a complete GeometryAcoustics renderer or a qualified UTD model.
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

// Called synchronously during iplSimulatorRunPathing on the registering thread.
// Arrays live only for the callback. Do not reenter simulation from the callback.
// Points use Steam's world coordinates in metres: source, retained probes, listener.
// Probe IDs belong to the current batch; -1 and -2 denote source and listener.
// Length is the complete validated polyline. Weight is applied once by the caller.
// EQ is the native selected probe-route deviation filter, without that weight.
// LOS is excluded. Use ias_probes_find for explicit coverage status.
// Interpolation source/listener IDs survive geometric simplification within a batch.
// Multiple probe representations can describe one route: these are not independent
// full-strength sound sources. Rebaking invalidates probe IDs.
typedef void (*IASPathCallback)(int count, const int* probe_ids,
                               const float* points_xyz, float length_m,
                               float interpolation_weight,
                               const float* eq_three_bands, int source_probe,
                               int listener_probe, void* user_data);

int ias_path_abi(void); // Returns 2.
void ias_path_capture(IASPathCallback callback, void* user_data); // NULL disables.

// Independent additive ABI for immutable, time-indexed scene snapshots.
// Inputs use Steam world metres. Returns 0, or -1 for invalid input.
// Geometry must be committed and must not mutate while being queried.
// Segment end is excluded; timed callers assign that point to the next epoch.
// Origin inclusion uses 10 micrometres of backward numerical tolerance.
int ias_visibility_abi(void); // Returns 1.
int ias_scene_segments(void* scene, int count, const float* starts_xyz,
                       const float* ends_xyz, unsigned char* blocked);

#ifdef __cplusplus
}
#endif

#ifdef __cplusplus
extern "C" {
#endif
// Automatic UniformFloor generation in native metre/Y-up bounds [min,max].
// Bake only static geometry. Always validate selected routes against the live scene.
// Create: positive probe count; -1 invalid input, -2 no floor probes,
// -3 configured capacity exceeded, -4 bake failure. Output owns its native data.
int ias_probes_abi(void); // Returns 1.
int ias_probes_create(void* static_scene, const float* bounds_min_max,
                     float spacing_m, float height_m, int max_probes, void** output);
void ias_probes_release(void* handle);
// Find: 0 completed (possibly no selected route), 1 LOS excluded;
// -1 invalid input, -2/-3 uncovered source/receiver,
// -4 no visible endpoint probes, -5 native failure. Register ias_path_capture first.
int ias_probes_find(void* handle, void* live_scene,
                    const float* source_xyz, const float* listener_xyz);
#ifdef __cplusplus
}
#endif
