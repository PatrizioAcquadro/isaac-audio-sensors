# Acoustic Provider Evaluation

Historical evidence through 2026-09-11; no new provider evaluation in this
consolidation. Distinguish executed engines, isolated components and inspection.
[[implementation_phases/r9-geometry-acoustics-provider-selection|R9]] owns selection;
[[experiments/geometry-acoustics-admission|Geometry Admission]] owns later native failures.

## Selected engine and withdrawn claims

Steam Audio 4.8.1 (`0da18255cca520771f363ee01f100572b39a308e`, Linux Release/Embree,
Apache-2.0) passed the original core-integration role through explicit geometric
arrival scheduling and assembly mapping. Direct raw output has no physical delay.
Historical complete-block p95 was 0.30/1.15 ms for one/four environments; refresh
p95 11.40/42.44 ms. These are the R9 fixture, not the later complete Geometry pipeline.

R9.4 admitted baked path search, dynamic validation/alternates and diagnostics,
but excluded the closed/paired transmission proxy: construction loss was not
predictable/additive. R10 later withdrew the stronger NLOS timing interpretation
because both scheduler and reference used straight distance. Native reflections'
absolute/inter-mic timing also failed. Historical reports are unchanged; broad
R10 admission never followed from core integration or byte-preserved reflection IRs.

## Candidate outcomes

| Candidate | Evidence type and result | Boundary |
| --- | --- | --- |
| NVIDIA RTX Acoustic 3.0.0 | Executed installed CHIRP/AM transmitter–receiver runtime | Active output, not arbitrary passive PCM/physical mic channels; installed proprietary distribution failed the required source-build path. No maintained executable surface |
| PRA 0.10.1 | Executed first-reflection controls, native visibility corrections and intermediate hybrid | Good specular candidate; not a full primary engine. Joint diffuse pressure/motion and general dynamic coverage remain open |
| gpuRIR | Documentation inspection | CUDA shoebox ISM does not cover arbitrary mesh/door input. Not installed/executed here |
| Habitat/SoundSpaces RLR | Repository/API inspection | Mesh/reflection/diffraction features, but inspected underlying engine archived/binary distribution and CC-BY-NC terms conflict with maintained open-source direction. Not executed |
| GSound/pygsound | Terms inspected; local Python 3.12 build attempted | Redistribution restrictions and bundled pybind11 build failure; no PCM qualification |
| RoomAcoustiCpp `241be79` | Native 3DTI Waveguide component executed | Moving distance 2→2.5 m should change delay 93.29→116.62 samples at 16 kHz; measured delay stays 93. Full scene not built; global pool/asynchronous lifecycle also needs work. Checked license LGPLv3, superseding old website wording |
| TASCAR `2e8b8b19b52a029af536383bfd59de2ee66db882` | Exact native diffuse-mic method compiled with buffer stubs | Normalized position enters `W + X*nx + Y*ny + Z*nz`; 0.02/0.10 m positions give identical pressure, bypassing point-source delay. Reject that component mapping, not every configuration; full runtime not built |
| PFFDTD `aa319f6c86517cb95aabfae8656277da62c3ead5` | Source inspection | Potential wave-based reference; inspected HDF5 boundaries/source/receiver indices are static. No retained-field dynamic USD interface found. Not run or acoustically rejected |
| DynamicSound, arXiv `2601.15433v1` | Paper inspection | Moving source/array delays and first-order planes; excludes occlusion/diffraction. Not a full indirect/diffuse solution; no runtime claim |

Steam W-only order-3 reconstruction was executed and failed like order zero.
Full-channel convolution crashed separately. Speaker/Ambisonics decoding uses
unit directions rather than displaced microphone coordinates. Parametric/hybrid
reverb and TAN were inspected, not qualified as microphone-timing repairs.
No evaluated alternative is currently a qualified whole-domain replacement.

## Evidence locations and source references

R9 reports/builds remain under ignored `build/qualification/r9/`; later controls
and replay pointers are in [[experiments/geometry-acoustics-admission|Geometry Admission]].
Temporary R9 adapters/runners/tests were removed; restore historical tooling only
in isolated evidence directories when an exact replay is necessary (`c59f830`).

Inspected sources (historical, not a new current survey):

- [Steam decode API](https://valvesoftware.github.io/steam-audio/doc/capi/ambisonics-decode-effect.html) and [reflection effects](https://valvesoftware.github.io/steam-audio/doc/capi/reflections-effect.html).
- [PRA source](https://github.com/LCAV/pyroomacoustics), [gpuRIR API](https://github.com/DavidDiazGuerra/gpuRIR).
- [Habitat audio](https://github.com/facebookresearch/habitat-sim/blob/main/docs/AUDIO.md), [RLR repository/license](https://github.com/facebookresearch/rlr-audio-propagation).
- [GSound inspected terms](https://github.com/GAMMA-UMD/pygsound/blob/8f41cb13da5dba9aa09cac3f42e668005ed5cf11/LICENSE.txt).
- [RAC inspected source/license](https://github.com/IoSR-Surrey/RoomAcoustiCpp/blob/241be79a07de4aeeb3d8f08ddfaa01b895b89712/ROOMACOUSTICPP_LICENSE).
- [TASCAR mic method](https://github.com/HoerTech-gGmbH/tascar/blob/2e8b8b19b52a029af536383bfd59de2ee66db882/plugins/src/receivermod_micarray.cc).
- [PFFDTD source](https://github.com/bsxfun/pffdtd/tree/aa319f6c86517cb95aabfae8656277da62c3ead5), [DynamicSound paper](https://arxiv.org/html/2601.15433v1).

## Consequence

Retain Steam direct/pathing and PRA specular capabilities behind one producer;
extend existing providers before reconsidering alternatives. The earlier absolute-
coverage stop was revised to [[decisions/robot-audition-fidelity|task-domain fidelity]].
New replacement evaluation requires the user decision after a concrete in-domain
failure. These component failures neither prove universal impossibility nor
justify silently adding another provider.
