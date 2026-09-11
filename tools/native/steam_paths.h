// Experimental selected-route interface for the patched Steam Audio 4.8.1 build.
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
// LOS is excluded. Empty capture does not distinguish no path from missing probes.
// Multiple probe representations can describe one route: these are not independent
// full-strength sound sources. Rebaking invalidates probe IDs.
typedef void (*IASPathCallback)(int count, const int* probe_ids,
                               const float* points_xyz, float length_m,
                               float interpolation_weight,
                               const float* eq_three_bands, void* user_data);

int ias_path_abi(void); // Returns 1.
void ias_path_capture(IASPathCallback callback, void* user_data); // NULL disables.

#ifdef __cplusplus
}
#endif
