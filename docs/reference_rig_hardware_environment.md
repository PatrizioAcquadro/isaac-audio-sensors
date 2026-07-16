# Reference Rig Hardware And Environment

Status: **Partial inventory; calibration measurements pending**  
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
| ReSpeaker geometry | Nominal/unknown | Manufacturer-listed microphone spacing is 66 mm. Exact microphone coordinates, acoustic centers, array axes, channel order, polarity, delay, and gain are not yet measured. |
| ReSpeaker firmware | Verified/target | Current live interface exposes two channels at 16 kHz using `S16_LE`. Target is the official six-channel USB firmware: two processed channels plus four raw microphone channels. The firmware version, binary hash, and post-flash ALSA format must be recorded. |
| Camera | Verified | Stereolabs ZED 2i connected directly to the workstation at USB 3, 5 Gb/s. The existing cable is adequate. |
| ZED software | Planned | ZED SDK was not installed at audit time. Install the current official Ubuntu 24/CUDA 12 build, record its hash/version, and avoid an unnecessary CUDA 13 migration. Update camera firmware only if the official ZED tool offers it. |
| Temporary speaker | Verified/limited | The user's MacBook built-in speakers may be used for pilot acquisition only. Exact Mac model is not yet recorded. |
| Reference speaker | Planned | One Genelec 8010A powered monitor is the selected repeatable source. It is required before final calibrated sim-vs-real claims, not before initial software and pilot work. |
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
- Hosa CYX-403M 3.5 mm TRS-to-dual-XLR cable for the powered monitor;
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

1. Flash and hash the official ReSpeaker six-channel USB firmware; verify all
   channels, formats, order, and playback.
2. Move the ReSpeaker to the Raspberry Pi and run capture, playback, disconnect,
   and long-run tests over the wired path.
3. Install and validate the official ZED SDK on the workstation.
4. Measure room dimensions, ReSpeaker geometry, ZED/ReSpeaker extrinsics, mount
   geometry, source poses, and uncertainty.
5. Acquire and characterize the reference monitor, UMIK-1, stands, and
   measurement tools.
6. Lock clock synchronization, acquisition metadata, and failure thresholds.
7. Obtain Alex mounting/access approval and verify the live onboard software.
8. Freeze serial numbers, firmware/software versions, calibrated profiles, and
   the final reference-rig BOM before S4 holdout collection.

Until these gates pass, describe the setup as an available four-microphone
development rig, not a calibrated research reference.

## External Technical References

- [ReSpeaker XVF3800 guide](https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/)
- [ZED SDK Linux installation](https://docs.stereolabs.com/docs/development/zed-sdk/linux)
- [ZED and Isaac ROS AprilTag example](https://docs.stereolabs.com/docs/integrations/isaac-ros/april-tag-detection)
- Alex003 Usage Guide: restricted Google Drive document; do not reproduce its
  credentials or restricted content.
