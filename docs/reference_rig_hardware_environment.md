# Reference Rig Hardware And Environment

Status: **Partial reference rig; sensor bring-up complete except audible ReSpeaker playback; calibration measurements pending**
Last verified: **July 16, 2026**

This document is the canonical record of the physical development rig for the
Isaac Audio Sensor and the later SquadBot bench work. It separates live-verified
facts from manufacturer specifications, documented Alex facts, and planned
equipment. It is not evidence that the rig is calibrated.

## Evidence Terms

- **Verified:** observed on the live hardware or host.
- **Nominal:** taken from manufacturer documentation; not independently measured.
- **Documented:** taken from the restricted Alex003 guide; not live-verified.
- **Planned:** selected but not yet acquired, installed, or validated.

## Reference Topology

```text
Temporary source: MacBook speakers
Final source: powered reference monitor
                    |
                    v
Room -> ReSpeaker XVF3800 -> USB -> Raspberry Pi 5
                                      |
                                wired Purdue LAN
                                      |
                                      v
                              RTX 4090 workstation
                                      ^
                                      |
                              USB 3 <- ZED 2i
```

The **workstation** is the Alienware desktop in the lab that runs Isaac Sim,
Isaac Lab, ZED tooling, and development workloads. The Raspberry Pi and
workstation are connected to the same wired Purdue subnet; they do not require
a direct cable, a private switch, or an additional Ethernet adapter.

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
| Temporary speaker | Verified/limited | The user's MacBook built-in speakers may be used for pilot acquisition only. Exact Mac model is not yet recorded. |
| Reference speaker | Planned | Current-but-not-frozen purchase direction: one Genelec 8030C powered monitor driven through a Focusrite Scarlett Solo USB interface. This supersedes the previously documented Genelec 8010A direction. It is required before final calibrated sim-vs-real claims, not before initial software and pilot work. The purchase BOM is not frozen. |
| Reference microphone | Planned | One serial-calibrated miniDSP UMIK-1 for level, response, noise, and room-response measurements. |
| Alex | Available/documented | Physical Alex003 fixed-torso platform and pedestal are available. Live compute access and mounting authorization still require verification. |

## Verified Network State

- Raspberry Ethernet and workstation Ethernet are active on the same Purdue
  wired subnet using DHCP.
- A 20-packet wired test produced 0% loss and RTT
  `min/avg/max/mdev = 0.129/0.202/0.412/0.060 ms`.
- Raspberry Wi-Fi and Tailscale remain available as fallback management paths.
- Wired reachability does not prove clock synchronization. A chrony/NTP or PTP
  policy, offset logging, and failure threshold must be locked before synchronized
  calibration capture.

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
- Native playback streams opened and completed on both hosts. Audible output
  through the ReSpeaker 3.5 mm connection was not physically confirmed, so the
  playback portion of the ReSpeaker gates remains open.
- Raspberry Pi disconnect/reconnect recovery passed, as did a two-second
  post-reconnect capture and a bounded 30-minute six-channel stream to
  `/dev/null`. No large audio artifact was added to the repository.

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

## Acoustic Environment

| Field | Current record |
| --- | --- |
| Location | Purdue University, WANG 2052 |
| Dimensions | Approximately 6.5 m x 3.0 m x 3.0 m; derived volume approximately 58.5 m3 |
| Floor | Carpet tiles; exact construction and absorption unknown |
| Ceiling | Suspended acoustic tiles with lighting and HVAC openings; exact material unknown |
| Walls and large surfaces | Painted walls, large whiteboards, mounted display, glass door/panel, and a hard conference table |
| Furniture | One long fixed table; 13 movable chairs; two movable waste bins |
| Reconfiguration | Chairs and bins may be repositioned; the table cannot be moved |

WANG 2052 is the first repeatable **meeting-room reference environment**, not an
anechoic or acoustically controlled room. Carpet and ceiling tiles provide some
absorption, while the table, whiteboards, display, glass, walls, and column create
strong reflections and occlusion opportunities.

Before calibration, measure the room and fixed-object geometry. Every accepted
take must record the door state, HVAC state, furniture layout, source and sensor
heights, temperature, humidity, and any people present.

## Source And Capture Controls

For MacBook pilot playback:

- use one versioned, checksummed lossless reference file;
- include a synchronization chirp;
- fix and record the output device, macOS version, volume, power state, pose,
  and distance;
- disable Spatial Audio, EQ, notification sounds, and other audio processing
  where controllable.

MacBook speakers are not the final reference source because their frequency
response, limiting, and device DSP are not fully controlled or portable. They
remain useful as an additional consumer-source robustness condition.

## Mounting And Measurement Equipment

No dedicated tripod, speaker stand, calibrated microphone, environmental meter,
turntable, or rigid ZED/ReSpeaker mount is currently available.

Selected equipment before S4 calibration:

- two K&M 201A/2 stands for the reference speaker and UMIK-1;
- Hosa CYX-403M 3.5 mm TRS-to-dual-XLR cable, previously selected for the
  Genelec 8010A setup; revalidate the cable choice against the current Genelec
  8030C and Focusrite Scarlett Solo direction before purchase;
- Bosch GLM165-25G laser distance meter;
- Klein Tools 935DAG digital angle gauge/level;
- iGaging 100-700-06 digital caliper;
- Komelon 4916IM 5 m metric/imperial tape;
- Testo 608-H1 temperature/humidity meter.

Do not buy a low-cost SPL meter if the calibrated UMIK-1 is acquired. A
traceable Class 2 meter/calibrator is a later decision only if the final claim
requires that level of metrology. A turntable is also deferred until pilot data
shows that marked poses plus visual tracking are insufficient.

## ZED And ReSpeaker Mount

The bench and Alex configuration require a rigid, removable bar that holds the
ZED 2i and ReSpeaker with a measured transform. The bracket should use a standard
tripod interface and preserve access to microphones, buttons, USB connectors,
and the camera field of view. Select the tripod and final bracket BOM only after
measuring both enclosures.

Printable AprilTag `tag36h11` markers may provide pose references for the ZED
workflow. Print them at a known size on a flat matte backing and attach them with
removable tape. Do not attach anything to Alex without authorization.

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

The available ZED 2i is USB and cannot use the documented ZED X Mini GMSL cable.
It therefore requires a non-invasive custom mount and an approved USB route.
Initially power the Raspberry Pi and sensors independently; do not modify Alex
power or electronics without IHMC approval. Exact onboard OS/ROS versions,
network access, and live sensor throughput remain unverified.

The Alex guide contains sensitive credentials. They must never be copied into
this repository, logs, datasets, or release artifacts.

## Remaining Gates

The ZED SDK installation and ZED 2i diagnostic, viewer, depth, IMU, stability,
and SVO checks are closed. The following reference-rig gates remain open:

1. Confirm audible ReSpeaker playback through its physical 3.5 mm output on the
   workstation and Raspberry Pi. Native ALSA playback streaming has passed on
   both hosts.
2. Measure room dimensions, ReSpeaker geometry, ZED/ReSpeaker extrinsics, mount
   geometry, source poses, and uncertainty.
3. Acquire and characterize the reference monitor, UMIK-1, stands, and
   measurement tools.
4. Lock clock synchronization, acquisition metadata, and failure thresholds.
5. Obtain Alex mounting/access approval and verify the live onboard software.
6. Freeze remaining serial numbers, calibrated profiles, and
   the final reference-rig BOM before S4 holdout collection.

Until these gates pass, describe the setup as an available four-microphone
development rig, not a calibrated research reference.

## External Technical References

- [ReSpeaker XVF3800 guide](https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/)
- [ZED SDK Linux installation](https://docs.stereolabs.com/docs/development/zed-sdk/linux)
- [ZED and Isaac ROS AprilTag example](https://docs.stereolabs.com/docs/integrations/isaac-ros/april-tag-detection)
- Alex003 Usage Guide: restricted Google Drive document; do not reproduce its
  credentials or restricted content.
