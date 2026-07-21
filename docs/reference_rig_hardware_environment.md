# Reference Rig Hardware And Environment

Status: **S4.1 and S4.2 passed for the installed handmade desktop fixture; S4.3 has not started**
Last verified: **July 16, 2026 hardware bring-up; July 20, 2026 operator report, photographic environment/fixture review, SSH/audio checks, and current-fixture ZED/audio capture; July 21, 2026 accepted S4.2 replacement capture, full SVO2 replay, machine-local validation, and clean-checkout repository gates**

This document is the canonical record of the physical development rig for the
Isaac Audio Sensor and the later SquadBot bench work. It separates live-verified
facts from manufacturer specifications, CAD-derived design references,
user-reported current setup, documented Alex facts, and planned work. It is not
evidence that the rig is absolutely calibrated or that either the temporary
fixture or future printed mount has passed formal physical or field acceptance.

## Evidence Terms

- **Verified:** observed on the live hardware or host.
- **Measured:** directly measured for the recorded test with the stated method
  and uncertainty; not necessarily metrology-grade.
- **CAD-derived:** taken or calculated from the released mechanical design;
  not an as-built optical/acoustic measurement.
- **Nominal:** taken from manufacturer documentation; not independently measured.
- **Approximate:** sufficient for the stated functional use but not a precision
  calibrated quantity.
- **User-reported:** reported as part of the current setup but not independently
  reverified by the dated hardware bring-up evidence.
- **Documented:** taken from the restricted Alex003 guide; not live-verified.
- **Planned:** selected but not yet acquired, installed, or validated.
- **Unmeasured:** no measurement is currently available.
- **Unsupported:** the available evidence cannot establish the quantity.

## Reference Topology

```text
Primary controlled source: MacBook speakers
Robustness sources: phone, voice, claps, impacts, ordinary objects
                    |
                    v
Room -> ReSpeaker XVF3800 -> USB -> Raspberry Pi 5
                                      |
                               Purdue network/SSH
                                      |
                                      v
                              RTX 4090 workstation
                                      ^
                                      |
                              USB 3 <- ZED 2i
```

The **workstation** is the fixed Alienware desktop at the WANG 2022 desk. It
runs Isaac Sim, Isaac Lab, ZED tooling, and development workloads. The ZED 2i
therefore remains directly attached to its verified rear USB 3 port. The
ReSpeaker attaches to the Raspberry Pi in the same test area; the workstation
controls that host through SSH. A July 20 live check from the current workstation
resolved `elab-raspberrypi5`, returned the expected hostname, and enumerated the
ReSpeaker playback device. Recordings are written locally before transfer rather
than treating network command timing as synchronization.

Tailscale and key-only SSH through the `elab-raspberrypi5` alias remain the
stable management path. Dataset traffic should prefer wired Ethernet. Exact
DHCP and Tailscale addresses are intentionally not tracked here.

## Hardware Inventory

| Component | State | Essential facts |
| --- | --- | --- |
| Lab workstation | Verified | Alienware Aurora R16; Ubuntu 24.04.4; NVIDIA RTX 4090; NVIDIA driver 580.159.03; CUDA 12.2 toolkit; Killer E3000 2.5 GbE. Local evidence uses Isaac Sim 6.0.1 and Isaac Lab 3.0.0. |
| Raspberry Pi | Verified | Raspberry Pi 5, 8 GB RAM; official black case; official 27 W USB-C supply; SanDisk Extreme 128 GB microSD available. Hostname and SSH alias: `elab-raspberrypi5`. |
| Raspberry software | Verified | Debian GNU/Linux 13 (`trixie`), ARM64, kernel `6.18.34+rpt-rpi-2712`; key-only SSH configured; password authentication disabled. |
| Microphone array | Verified | Seeed Studio ReSpeaker XVF3800 USB 4-Mic Array with case; four-microphone circular array; USB Audio device detected at USB 2 speed. |
| ReSpeaker geometry | Nominal/partially verified | Manufacturer-listed microphone spacing is 66 mm. The official control interface reports the configured microphone coordinates as `(0.033, -0.033, 0)`, `(0.033, 0.033, 0)`, `(-0.033, 0.033, 0)`, and `(-0.033, -0.033, 0)` m. Acoustic centers, array axes relative to the enclosure, polarity, delay, and gain are not yet physically measured. |
| ReSpeaker firmware | Verified | ReSpeaker serial `114993701261100454`; official six-channel USB firmware `2.0.8`; native ALSA capture is six-channel, 16 kHz, `S16_LE`. Firmware binary SHA-256: `8dd27762ebd87a28f0b4546f1634ece5e7eae308375d66952f7a9e3fb948266a`. |
| Camera | Verified | Stereolabs ZED 2i serial `39011785`, camera firmware `1523`, sensor firmware `777`; connected directly to a rear workstation USB 3 port at 5 Gb/s. An initially selected USB port produced protocol errors and resets; changing rear ports produced clean two- and ten-minute tests. |
| ZED software | Verified | Full official ZED SDK `5.4.0` for Ubuntu 24/CUDA 12 installed at `/usr/local/zed`, including tools, samples, Python support, TensorRT 10.9, and neural depth models. NVIDIA driver `580.159.03` and CUDA toolkit `12.2` were preserved. Installer SHA-256: `bab3ae693865225b0e2cac2b09dadd0c520ce245a011a8e3785037ec46f1f811`. |
| Primary controlled source | User-reported/limited | The user's MacBook built-in speakers are the primary S4 controlled source. The exact Mac identity, WAV, volume, pose, distance, orientation, and relevant settings are recorded per comparable take. Its source-room transfer and internal DSP are not isolated. |
| Robustness sources | User-reported/limited | Phone, human voice, claps, impacts, and ordinary objects are available for robustness trials; they are not primary calibration references. |
| Specialized acoustic source/reference | Not required for current functional testing | No professional reference speaker, dedicated Focusrite-class interface, UMIK-1/calibrated microphone, certified SPL meter, or acoustic calibrator is required for S4. Add one later only if an advertised final claim or observed blocker establishes the need. |
| Placement and orientation aids | User-reported | Metric tape, printed angular reference, and an iPhone level application are available for practical placement and basic orientation checks. |
| Current functional fixture | User-reported/photographically reviewed | `S4_TEMP_DESKTOP_FIXTURE_REV0`: ZED below and ReSpeaker above on two fixed inverted plastic supports, all held in place on a corrugated-cardboard desktop riser. The operator reports that neither support nor sensor detaches or moves in use. Tape-measured approximate ReSpeaker-center position relative to the ZED stereo midpoint is `(-0.085, 0.000, +0.095) m` in project `(+X forward, +Y right, +Z up)`, with `+/-0.005 m` practical measurement uncertainty per component; the `+Z` value is the midpoint of the reported `90-100 mm` range. The ZED lens midpoint is `0.055 +/- 0.005 m` above the desktop, or approximately `0.755 m` above the floor when combined with the approximate `0.70 m` desk height. These are approximate as-used quantities, not calibrated extrinsics. The fixture footprint and all three project axes are physically marked. |
| Alex | Available/documented | Physical Alex003 fixed-torso platform and pedestal are available. Live compute access and mounting authorization still require verification. |

## Verified Network State

- Raspberry Ethernet and workstation Ethernet are active on the same Purdue
  wired subnet using DHCP.
- A 20-packet wired test produced 0% loss and RTT
  `min/avg/max/mdev = 0.129/0.202/0.412/0.060 ms`.
- Raspberry Wi-Fi and Tailscale remain available as fallback management paths.
- SSH reachability from the WANG 2022 workstation passed on July 20, 2026. The
  first accepted take still requires the planned local audio/ZED capture check.
- Wired reachability does not prove clock synchronization. S4 records the
  time-association method and uncertainty appropriate to each metric. Chrony/NTP,
  PTP, or additional timing hardware is required only when practical per-take
  chirp/clap/visible-impact alignment cannot support the claimed metric.

No Ethernet switch, USB Ethernet adapter, or replacement ZED cable is currently
required.

## Sensor Bring-Up Evidence

The official standalone hardware bring-up was performed on July 16, 2026. It
did not execute or change the status of roadmap phase S0. The dated report is
[`evidence/2026-07-16_reference_rig_hardware_bringup.md`](evidence/2026-07-16_reference_rig_hardware_bringup.md),
and the sanitized official ZED Diagnostic result is
[`evidence/2026-07-16_zed_diagnostic_sanitized.json`](evidence/2026-07-16_zed_diagnostic_sanitized.json).

### ReSpeaker XVF3800

- Before upgrade, USB device `2886:001a`, serial
  `114993701261100454`, exposed two native capture channels at 16 kHz
  `S16_LE`; the official control interface returned firmware `2.0.6`.
- The complete official repository was cloned from
  `https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY` at commit
  `e4c2073e1470180746580a6ba5468c9bf45026e1`. The selected binary was
  `xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_6chl_v2.0.8.bin`,
  SHA-256
  `8dd27762ebd87a28f0b4546f1634ece5e7eae308375d66952f7a9e3fb948266a`.
- `dfu-util` 0.11 enumerated alternate 1 as `reSpeaker DFU Upgrade` and
  alternate 0 as `reSpeaker DFU Factory`. Only alternate 1 was written using
  the official command. The factory alternate was not touched.
- After power cycling, the official control interface returned firmware
  `2.0.8`, the geometry listed above, and a live DOA value. No algorithm
  parameters were changed.
- Native hardware probing on both the workstation and Raspberry Pi found six
  capture channels at 16 kHz `S16_LE`. This differs from the manufacturer's
  32-bit description; the USB descriptor reports a two-byte subslot and ALSA
  rejects `S32_LE`, so `S16_LE` is recorded as the verified hardware format.
- The official channel map is channel 0 Conference, channel 1 ASR, and channels
  2 through 5 raw microphones 0 through 3. Ten-second six-channel captures on
  both hosts were valid PCM WAV files. Every channel was non-silent; raw channel
  pairs were not sample-identical. The workstation capture had one negative
  full-scale sample on channel 0 but no sustained clipping; the Raspberry
  capture had no full-scale samples.
- Native playback streams opened and completed on both hosts. A July 20 WANG
  2022 SSH check enumerated the ReSpeaker as ALSA playback `card 2, device 0`.
  The device exposes stereo `PCM,0` and mono `PCM,1` playback controls.
- Audible output through the ReSpeaker 3.5 mm connection was physically
  confirmed on July 20 using known-good headphones and a `speaker-test` 1 kHz
  stereo sine stream at 48 kHz `S16_LE`. The operator heard the signal at
  `PCM,0 = 70%` (`-18 dB`); the earlier `35%` (`-39 dB`) attempt was inaudible.
  After the check, `PCM,0` was returned to `55%` (`-27 dB`). This verifies the
  analog-output path but is not a frequency-response, SPL, or fidelity
  calibration.
- Raspberry Pi disconnect/reconnect recovery passed, as did a two-second
  post-reconnect capture and a bounded 30-minute six-channel stream to
  `/dev/null`. No large audio artifact was added to the repository.
- A July 20 current-fixture capture produced a 20.000-second, six-channel,
  16 kHz, `S16_LE` WAV. All six channels were non-silent, no channel contained
  a full-scale sample, and the prompted transient was most evident on processed
  channel 0. SHA-256:
  `80e077b02a5d0dda047311e9c891fa74ab125de41cdd8d128139083c3ee1f7eb`.
  This passes the S4.1 local audio-integrity check; raw-channel event/DOA and
  audio-video alignment checks were subsequently closed by the S4.2
  replacement take described below.
- The July 21 S4.2 replacement attempt
  `s4_2_20260721T153800Z_optimized_candidate_014` retained 35.000 seconds of
  six-channel audio, a 1,052-frame HD720/30 FPS SVO2 and JSONL record, the full
  9.5-second reference playback, and the two-second post-playback margin. Full
  ZED SDK replay and representative image/depth/IMU/pose retrieval passed. The
  visible/audible impact association is `-1.855323 s` using the documented
  `ZED elapsed - audio elapsed` definition, with `37.366880 ms` uncertainty.

### ZED 2i

- The official interactive installer
  `ZED_SDK_Ubuntu24_cuda12.8_tensorrt10.9_v5.4.0.zstd.run`, SHA-256
  `bab3ae693865225b0e2cac2b09dadd0c520ce245a011a8e3785037ec46f1f811`,
  installed the full SDK `5.4.0` at `/usr/local/zed`. The existing NVIDIA
  driver and CUDA 12.2 toolkit were compatible and were not changed.
- The official ZED Diagnostic command completed successfully. It verified ZED
  SDK 5.4.0, CUDA operations on the RTX 4090, the ZED 2i, USB 3 bandwidth, and
  the optimized neural depth models. Its OpenGL warning came from the
  non-graphical command-line session; the official graphical tools subsequently
  started and operated normally.
- The SDK API verified serial `39011785`, camera firmware `1523`, sensor
  firmware `777`, and left, right, neural-depth, and IMU data at HD720 and
  60 FPS. The official SDK ships ZED 2i firmware `1523`, matching the camera;
  no firmware update was required or performed.
- The user visually confirmed that ZED Explorer, ZED Depth Viewer, and ZED
  Sensor Viewer all start and work. Objective API testing separately confirmed
  USB 3 operation, HD720 at 60 FPS, left/right/depth retrieval, and IMU reads.
- The first ten-minute test on the original USB port failed: the kernel logged
  repeated UVC protocol error `-71`, two physical disconnect/re-enumeration
  events, and the SDK recovered twice. After reseating the cable and moving it
  to a different direct rear USB 3 port, a 120.007-second precheck passed with
  7,200 grabs and a clean 600.016-second acceptance test passed with 35,998
  grabs, zero API failures, 600 left/right/depth checks, 600 successful sensor
  reads, and no reset or recovery. The maximum image timestamp gap was
  33.389 ms.
- A 10.031-second H.264 SVO2 recording outside Git contains 302 HD720@30
  frames. Its size is 17,209,314 bytes and its SHA-256 is
  `e0030e9217dd17471e71726681c0fd2c00c3f043b7e48dc8ec90725625c4ed2d`.
  No manual camera calibration was run because ZED Diagnostic did not require
  it.
- A July 20 host-visible current-fixture check at HD720@30 captured 299 image,
  depth, and sensor reads in 10.381 seconds with zero grab failures and strictly
  increasing image timestamps. A saved left frame has SHA-256
  `4f924b51f2be0fa5b3a69d29dd09dbb98fa3126e2e22bd6227b16c8bf0f8e1a2`.
  Electronic capture passed, but practical FOV acceptance did not: the
  cardboard riser occupied approximately the lower third of the image. The
  required corrective action was to move the complete fixed sensor assembly
  forward so the ZED face reached or slightly overhung the riser edge, remark
  the footprint, and rerun before closing S4.1.
- The operator moved the complete fixed assembly to the front edge without
  changing the relative ZED/ReSpeaker geometry and remarked its footprint. The
  host-visible rerun captured 300 image, depth, and sensor reads in 10.381
  seconds with zero grab failures, strictly increasing timestamps, and a
  66.653 ms maximum observed image-timestamp gap. Visual review confirmed that
  the cardboard obstruction was eliminated. The rerun left-frame SHA-256 is
  `ee521792e61f9db1fdcee8fc4ee90dabba6855af4a5d6f041f3cd462ee964651`.
  This passes the current-fixture electronic and practical ZED FOV checks, but
  the raw frame remains outside versioned evidence because a person is
  partially visible at the right edge. A separate July 20 host-visible rerun
  using the tracked `scripts/run_s4_1_zed_fixture_check.py` also passed 300
  image/depth/sensor reads with zero grab failures and strictly increasing
  timestamps. Full-resolution review of the unaltered final frame found no
  person, readable screen content, label, or personal identifier. Its SHA-256
  is `4fd766f8377b4661ee4bdd761740b710bfc88f9dfe143ff1302d9b5c9ecc289b`.

## Acoustic Environment

The current primary functional environment is the fixed workstation area near
the entrance of Purdue University WANG 2022. WANG 2052 remains a documented
earlier candidate/possible robustness environment; it is not the primary joint
ZED/ReSpeaker environment because the verified ZED host is a fixed workstation.

| Field | Current WANG 2022 record |
| --- | --- |
| Overall geometry | Approximately `13.5 m x 8 m x 3 m`; open office/cubicle area rather than a closed small room. |
| Local rig-to-boundary geometry | Relative to the ZED facing direction: approximately `3.3 m` to the wall in front, `0.55 m` behind the rig, `0.3 m` to rig-left, and `5.5 m` to the structural wall on rig-right; the area opens toward behind-left. |
| Desk | User-reported wood desk, approximately `0.61 m x 1.35 m`, surface height approximately `0.70 m`. The temporary fixture currently sits on a corrugated-cardboard riser on this desk. |
| Floor | Carpet tiles; exact construction and absorption unknown. |
| Ceiling | Suspended acoustical ceiling-tile grid with recessed lighting troffers and visible air supply/return grilles. HVAC operating state is unconfirmed; the operator reports no audible HVAC noise. |
| Walls and partitions | Painted gypsum-board walls plus rigid cubicle partitions with translucent upper panels. There are no soft acoustic dividers at the test station. |
| Nearby fixed objects | Two fixed monitors are visible behind/near the rig, the fixed workstation tower is below the desk, and a filing cabinet and cubicle partitions are close to the station. The ReSpeaker is approximately `0.20 m` from the nearest fixed monitor. Their state is held fixed for controlled repetitions. The third screen visible in the photographs is the movable MacBook controlled source, not a fixed monitor. |
| Wider open-space objects | Other cubicles, desks, chairs, cabinets, a door, and distant windows with blinds are visible in the supplied photographs. No nearby exterior window is reported at the test station. |
| Occupancy | Four people normally use the larger open-space; controlled takes target zero other people present. |
| Noise | Operator reports the area is normally quiet, without routine corridor, printer, machinery, or speech noise. Workstation fans are variable but usually quiet and may become more audible during Isaac training. |
| Source-placement access | The photographed MacBook is the movable controlled source. Placement is available in front, behind, and to either side. A workstation/cubicle divider may occlude some front paths; exact allowed distance/angle cells are frozen in the S4.2/S4.3 runbook. |
| Reconfiguration | Chairs and wider-area occupancy can vary. Monitors and the test-station layout are reported fixed for controlled takes; every accepted take records deviations. |

Nine user-supplied fixture/environment photographs were reviewed on July 20,
2026. They support the qualitative layout, fixed-fixture claim, footprint
marks, and project-axis orientation above but are not yet copied into the
versioned S4.1 evidence root. Their source attachment names and SHA-256
identities are retained for later selection and sanitization:

| Photograph | SHA-256 | Archival note |
| --- | --- | --- |
| `codex-clipboard-0fa0efdb-2ebc-44d1-b73c-c028fe31dc06.png` | `1dd0e5418e5240d23ebef869094fbac21a3d0633b59d3451cea5cb805a3e2c63` | Close fixture view; sanitize before versioning. |
| `codex-clipboard-ba9b616a-2bc5-43e6-af80-8ec295728354.png` | `022c41e33bef84787b20fda157a5434e4ee487883f3afa0399d71b426a3fb278` | Wide environment view; sanitize before versioning. |
| `codex-clipboard-6945a2d1-6100-44f8-be5d-ec677e021741.png` | `feb9d60d70c6b416d45def53988bcdeedf794b7594bbc282124ec800353eeb4e` | Wide environment view; sanitize people/background before versioning. |
| `codex-clipboard-acfc9631-abc7-475c-a61b-103796f9fb76.png` | `991de1c4610776bad8aebd724e04e5e5324b6f8833441e3acd5d171c1fbd63d2` | Wide environment view; sanitize before versioning. |
| `codex-clipboard-de1f5ef9-75eb-4a6e-9f40-89b53b1de4fd.png` | `64bde314c83f9f6b6350a911d4022300f806439b4540bce3ac944565550e8cb8` | Test-station view; sanitize before versioning. |
| `codex-clipboard-ec17d964-843c-491b-8200-8316eec2d7c1.png` | `06b0c59d6bb0ffedc1c0ad8181ea67da2b011810a86c660894e69c9a84f16214` | Top view showing footprint and `+X`/`+Y`; candidate after sanitization. |
| `codex-clipboard-0be62b66-1665-406c-b31c-78fb6f87a7d0.png` | `5192a01c5ff76911b7e4ff4fe02ec950275a56b799f43691585866f5611ca55d` | Do not version as supplied: shipping label contains personal information; crop or redact first. |
| `codex-clipboard-99bc8f2e-6ad7-4ff3-95cb-61174a6f3ce8.png` | `420f74e7b0202b376686839415c264c3cf3f603fea68087c40f296d895d005cc` | Angled fixture/axis view; candidate after sanitization. |
| `codex-clipboard-4e959e9c-f810-4ced-bb07-2101e83f0e68.png` | `fd7d188d131563cfd3f0605598ea1d01ff8f5231664d6789fbda1c76b38418f3` | ReSpeaker connector view; candidate after sanitization. |

Before closeout, copy the selected sanitized photographs into the S4.1
evidence package and verify these hashes. The operator corrected the
ReSpeaker-to-nearest-fixed-monitor distance to approximately `0.20 m` and
confirmed that both ZED and ReSpeaker are approximately `5.5 m` from the right
structural wall. A physical outline has been marked to reproduce the fixture's
desk placement, so a ZED-to-desk-edge distance is not required for the current
placement method. The physical project axes use the package convention: local
`+X` forward along the ZED viewing direction, local `+Y` right as viewed from
the ZED (the operator's left while facing the camera), and local `+Z`
vertically upward. This wording was corrected on July 21 before any S4.3 trial
to match the authoritative S4.1 frame lock; the machine-readable frame lock
itself did not change. The photographed `+X` and `+Y` arrows are consistent
with this convention. On July 20 the operator confirmed that the
`+Z`-up mark was subsequently added; no additional photograph was required for
this user-reported fixture-state update.

Physical instructions use the explicit `F_operator_facing_zed` frame first.
For an operator standing in front of and facing the ZED: +X is behind the
operator/in front of the ZED, -X is in front of the operator/behind the ZED,
+Y is the operator's right, -Y is the operator's left, +Z is ceiling/up, and
-Z is floor/down. It shares the `F_project` origin. Conversion to the canonical
software frame is `(x, y, z)_project = (x, -y, z)_operator` and
`bearing_project = (-bearing_operator) mod 360`.

WANG 2022 is a repeatable **open-office functional environment**, not an
anechoic or acoustically controlled room. Carpet and ceiling tiles provide some
absorption, while the desk, cardboard riser, monitors, cubicle panels, cabinets,
walls, ceiling, and wider office create reflections and occlusion opportunities.

Before controlled functional characterization, record enough room and
fixed-object geometry to reproduce placement and interpret the target metrics.
Every accepted take records the room, source and sensor poses, door/HVAC and
materially relevant furniture/people state. Temperature and humidity are
recorded when available or needed for the claim; missing environmental values
are labeled rather than silently invented or made automatic blockers.

## Source And Capture Controls

For controlled MacBook playback:

- use one versioned, checksummed lossless reference file;
- include a synchronization chirp;
- fix and record the output device, macOS version, volume, power state, pose,
  and distance;
- disable Spatial Audio, EQ, notification sounds, and other audio processing
  where controllable.

MacBook speakers support repeatable functional claims within the recorded
configuration and controlled variation across recorded WAV, volume, pose,
distance, and angle ranges. Their combined source-room-sensor frequency
behavior, limiting, and device DSP do not support isolated speaker response,
absolute SPL, or universal transfer. Phone, voice, claps, impacts, and ordinary
objects remain separate robustness conditions.

## Mounting And Measurement Equipment

The current functional setup uses the operator-built, handmade
`S4_TEMP_DESKTOP_FIXTURE_REV0`, metric tape, a printed angular reference, and an
optional iPhone level application. The operator reports that the two inverted
plastic supports, ReSpeaker, and ZED are fixed and do not detach or move in
use. Photographs show this actual fixture on a corrugated-cardboard riser at
the WANG 2022 workstation. Existing furniture, rooms, and free Purdue resources
may be used where they support safe, repeatable testing. No tripod or printed
CAD mount is part of the current fixture.

Current S4 does not require purchases of a professional reference speaker,
dedicated audio interface, calibrated reference microphone, speaker/microphone
stands, tripod, laser distance meter, digital caliper, dedicated digital level,
AprilTags, turntable, certified SPL meter/calibrator, cosmetic cable management,
or formal mount-qualification accessories. Introduce a more precise tool later
only when a required final claim or observed uncertainty cannot be resolved by
the functional procedure and available evidence.

## ZED And ReSpeaker Mount

[ZED 2i / ReSpeaker Mount Model And Development Handoff](zed_respeaker_mount_model_handoff.md)
is the repository-level record for a future printed design, not the installed
S4.1 mount.
Revision A Option 1 is reported digitally complete and released in the external
companion CAD project, but its exact transform and sealed release were not
retrievable during S4.1 closeout. That does not block the different handmade
fixture. Revision A Option 1 is not yet fabricated;
filament/procurement preparation is in progress. It remains the planned future
mount and uses a detachable steel-ballasted table base. The historical
[pre-CAD input lock](zed_respeaker_mount_pre_cad.md) remains useful
context but does not override the completed design.

The CAD-derived sensor mechanical centers are nominally separated by `90 mm`.
That dimension and the nominal CAD transform are mechanical design references,
not measured optical/acoustic extrinsics or as-built calibration. The temporary
fixture's operator-reported center-to-center separation is approximately
`90-100 mm`, visually consistent with the CAD design intent but not the CAD
assembly or a measured transform. Neither fixture has a measured optical/
acoustic extrinsic; the future printed assembly has not been physically or field
accepted.

Current S4 evidence identifies the installed handmade configuration only as
`S4_TEMP_DESKTOP_FIXTURE_REV0`. Every accepted take records that mount identity
and actual state. A future printed Revision A Option 1 mount receives a distinct
identity, new as-built pose and uncertainty measurements, and practical/bridge
testing before any existing profile or result is claimed to transfer.

For initial S4 functional testing, check and record only that the rig does not
move unintentionally, the support remains stable during the planned test, the
pose is reproducible enough for the target metrics, microphone openings and the
camera field of view remain sufficiently unobstructed, and cable routing is safe
and does not disturb the rig. Formal torque, adhesive, lifecycle, proof-pull,
precision-deflection, and mount-metrology gates in the companion release remain
pending physical-qualification work; they are not automatic blockers for safe,
repeatable functional testing and must not be claimed as passed.

## Alex Integration Boundary

The restricted Alex003 guide documents:

- a 16-DoF fixed-torso manipulator on a pedestal;
- an ASRock 1360P/D5 NUC with an Intel i7-1360P, 32 GB RAM, PREEMPT_RT, and the
  low-level EtherCAT controller;
- an NVIDIA AGX Orin 64 GB with 1 TB NVMe for routing, logging, perception, and
  AI workloads;
- ROS 2 communication through Fast DDS with domain ID 42;
- a head location and routed GMSL cable intended for a ZED X Mini, but no
  delivered camera or mount.

This is authoritative evidence of an intended camera provision, not proof that
a ZED X Mini or any other camera is installed on Alex now. Before V14-15, verify
the actual installed camera model from the unit-specific model, approved robot
records, or live inventory. Use that camera when appropriate; do not require the
bench USB ZED 2i on Alex merely to reproduce the bench configuration. Record a
functionally sufficient ReSpeaker-to-installed-camera pose instead of reusing
the bench nominal transform.

A simple non-permanent ReSpeaker installation is acceptable when it is stable,
safe, documented, and repeatable enough for the planned validation. Add straps,
specialized hardware, or more precise metrology only if actual safety,
stability, association, or final-claim evidence requires them. Initially power
the Raspberry Pi and sensors independently; do not modify Alex power or
electronics without IHMC approval. Exact onboard OS/ROS versions, camera model,
network access, and live sensor throughput remain unverified.

The Alex guide contains sensitive credentials. They must never be copied into
this repository, logs, datasets, or release artifacts.

## Remaining Gates

The ZED SDK installation and ZED 2i diagnostic, viewer, depth, IMU, stability,
and SVO checks are closed. S4.1 passed for the installed handmade fixture. The
functional fixture work closes the current
device/channel/frame/room/topology record, approximate as-used geometry, marked
placement, practical mount/FOV/cable checks, SSH, audible playback, six-channel
local audio capture, and current-fixture ZED capture. The unavailable future
CAD package is not evidence for this fixture and is not an S4.1 blocker.
Formal printed-mount physical acceptance remains separate. The S4.2 replacement
take retains the complete reference playback and passes blocking offline SVO2
replay and retained-data validation. Its startup path uses stable-session
Mac/GPU checks and actual-recorder readiness rather than redundant per-take
probes. S4.2 repository closeout passed from the authorized frozen commit,
raw-independent clean-checkout validation, and provenance-bound Kit/pack
audits. S4.3 has not started. The
following later gates remain open:

1. Lock acquisition metadata, practical time-association/alignment, data-quality
   rules, compact controlled matrix, stopping rule, and failure thresholds.
2. Freeze development/fit and held-out groups, supported fields, criteria, and
   hashes before final held-out evaluation.
3. If the 3D-printed mount is fabricated, assign a new mount identity, measure
   its as-built sensor pose and uncertainty, and rerun practical fixture checks.
4. Obtain Alex access/installation approval; verify the actual installed camera,
   compute/network behavior, and live software before claiming real Alex
   validation.

The absence of professional acoustic/metrology equipment is not an S4 blocker.
Claims may now describe supported functional evidence inside
the documented envelope, but not absolute calibration, universal transfer, or
measured optical/acoustic extrinsics without additional evidence.

## External Technical References

- [ReSpeaker XVF3800 guide](https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/)
- [ZED SDK Linux installation](https://docs.stereolabs.com/docs/development/zed-sdk/linux)
- Alex003 Usage Guide: restricted Google Drive document; do not reproduce its
  credentials or restricted content.
