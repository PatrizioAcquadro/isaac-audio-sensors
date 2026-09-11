"""Private ABI declarations for the qualified Steam Audio 4.8.1 build."""

import ctypes


class _Vector3(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float), ("z", ctypes.c_float)]


class _AudioSettings(ctypes.Structure):
    _fields_ = [("sampling_rate", ctypes.c_int32), ("frame_size", ctypes.c_int32)]


class _DirectEffectSettings(ctypes.Structure):
    _fields_ = [("num_channels", ctypes.c_int32)]


class _DirectEffectParams(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_int),
        ("transmission_type", ctypes.c_int),
        ("distance_attenuation", ctypes.c_float),
        ("air_absorption", ctypes.c_float * 3),
        ("directivity", ctypes.c_float),
        ("occlusion", ctypes.c_float),
        ("transmission", ctypes.c_float * 3),
    ]


class _AudioBuffer(ctypes.Structure):
    _fields_ = [
        ("num_channels", ctypes.c_int32),
        ("num_samples", ctypes.c_int32),
        ("data", ctypes.POINTER(ctypes.POINTER(ctypes.c_float))),
    ]


class _DistanceAttenuationModel(ctypes.Structure):
    _fields_ = [
        ("model_type", ctypes.c_int),
        ("min_distance", ctypes.c_float),
        ("callback", ctypes.c_void_p),
        ("user_data", ctypes.c_void_p),
        ("dirty", ctypes.c_int),
    ]


class _CoordinateSpace3(ctypes.Structure):
    _fields_ = [
        ("right", _Vector3),
        ("up", _Vector3),
        ("ahead", _Vector3),
        ("origin", _Vector3),
    ]


class _AirAbsorptionModel(ctypes.Structure):
    _fields_ = [
        ("model_type", ctypes.c_int),
        ("coefficients", ctypes.c_float * 3),
        ("callback", ctypes.c_void_p),
        ("user_data", ctypes.c_void_p),
        ("dirty", ctypes.c_int),
    ]


class _Directivity(ctypes.Structure):
    _fields_ = [
        ("dipole_weight", ctypes.c_float),
        ("dipole_power", ctypes.c_float),
        ("callback", ctypes.c_void_p),
        ("user_data", ctypes.c_void_p),
    ]


class _Sphere(ctypes.Structure):
    _fields_ = [("center", _Vector3), ("radius", ctypes.c_float)]


class _BakedDataIdentifier(ctypes.Structure):
    _fields_ = [
        ("data_type", ctypes.c_int),
        ("variation", ctypes.c_int),
        ("endpoint_influence", _Sphere),
    ]


class _DeviationModel(ctypes.Structure):
    _fields_ = [
        ("model_type", ctypes.c_int),
        ("callback", ctypes.c_void_p),
        ("user_data", ctypes.c_void_p),
    ]


class _SimulationSettings(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_int),
        ("scene_type", ctypes.c_int),
        ("reflection_type", ctypes.c_int),
        ("max_num_occlusion_samples", ctypes.c_int32),
        ("max_num_rays", ctypes.c_int32),
        ("num_diffuse_samples", ctypes.c_int32),
        ("max_duration", ctypes.c_float),
        ("max_order", ctypes.c_int32),
        ("max_num_sources", ctypes.c_int32),
        ("num_threads", ctypes.c_int32),
        ("ray_batch_size", ctypes.c_int32),
        ("num_vis_samples", ctypes.c_int32),
        ("sampling_rate", ctypes.c_int32),
        ("frame_size", ctypes.c_int32),
        ("opencl_device", ctypes.c_void_p),
        ("radeon_rays_device", ctypes.c_void_p),
        ("tan_device", ctypes.c_void_p),
    ]


class _SourceSettings(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_int)]


class _SimulationInputs(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_int),
        ("direct_flags", ctypes.c_int),
        ("source", _CoordinateSpace3),
        ("distance_attenuation_model", _DistanceAttenuationModel),
        ("air_absorption_model", _AirAbsorptionModel),
        ("directivity", _Directivity),
        ("occlusion_type", ctypes.c_int),
        ("occlusion_radius", ctypes.c_float),
        ("num_occlusion_samples", ctypes.c_int32),
        ("reverb_scale", ctypes.c_float * 3),
        ("hybrid_reverb_transition_time", ctypes.c_float),
        ("hybrid_reverb_overlap_percent", ctypes.c_float),
        ("baked", ctypes.c_int),
        ("baked_data_identifier", _BakedDataIdentifier),
        ("pathing_probes", ctypes.c_void_p),
        ("vis_radius", ctypes.c_float),
        ("vis_threshold", ctypes.c_float),
        ("vis_range", ctypes.c_float),
        ("pathing_order", ctypes.c_int32),
        ("enable_validation", ctypes.c_int),
        ("find_alternate_paths", ctypes.c_int),
        ("num_transmission_rays", ctypes.c_int32),
        ("deviation_model", ctypes.POINTER(_DeviationModel)),
    ]


class _SimulationSharedInputs(ctypes.Structure):
    _fields_ = [
        ("listener", _CoordinateSpace3),
        ("num_rays", ctypes.c_int32),
        ("num_bounces", ctypes.c_int32),
        ("duration", ctypes.c_float),
        ("order", ctypes.c_int32),
        ("irradiance_min_distance", ctypes.c_float),
        ("pathing_vis_callback", ctypes.c_void_p),
        ("pathing_user_data", ctypes.c_void_p),
    ]


class _ReflectionEffectSettings(ctypes.Structure):
    _fields_ = [
        ("effect_type", ctypes.c_int),
        ("ir_size", ctypes.c_int32),
        ("num_channels", ctypes.c_int32),
    ]


class _ReflectionEffectParams(ctypes.Structure):
    _fields_ = [
        ("effect_type", ctypes.c_int),
        ("ir", ctypes.c_void_p),
        ("reverb_times", ctypes.c_float * 3),
        ("eq", ctypes.c_float * 3),
        ("delay", ctypes.c_int32),
        ("num_channels", ctypes.c_int32),
        ("ir_size", ctypes.c_int32),
        ("tan_device", ctypes.c_void_p),
        ("tan_slot", ctypes.c_int32),
    ]


class _PathEffectParams(ctypes.Structure):
    _fields_ = [
        ("eq_coeffs", ctypes.c_float * 3),
        ("sh_coeffs", ctypes.POINTER(ctypes.c_float)),
        ("order", ctypes.c_int32),
        ("binaural", ctypes.c_int),
        ("hrtf", ctypes.c_void_p),
        ("listener", _CoordinateSpace3),
        ("normalize_eq", ctypes.c_int),
    ]


class _SimulationOutputs(ctypes.Structure):
    _fields_ = [
        ("direct", _DirectEffectParams),
        ("reflections", _ReflectionEffectParams),
        ("pathing", _PathEffectParams),
    ]
