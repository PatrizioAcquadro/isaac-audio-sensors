# S0.5 reference-rig inventory closeout

| Field | Recorded value |
| --- | --- |
| Subphase | `S0.5` - Reference-rig inventory |
| Closeout date | 2026-07-16 |
| Entry revision | `1d663c9` (`1d663c99e53651cbaf04c93efeda68438409e32d`) |
| Canonical source | [`docs/reference_rig_hardware_environment.md`](../../../reference_rig_hardware_environment.md) |
| Canonical source last verified | July 16, 2026 |
| Evidence-label glossary | [`Evidence Terms`](../../../reference_rig_hardware_environment.md#evidence-terms) in the canonical source |

## Scope

This closeout maps every reference-rig field required by Section 6.3 of
[`docs/final_sensor_development_plan.md`](../../../final_sensor_development_plan.md#63-s0---baseline-and-acceptance-lock)
to the canonical hardware and environment record. The canonical source remains
the authority for the inventory; this closeout does not promote any evidence
label or fill any unknown value.

The evidence labels below retain their canonical meanings: **Verified** facts
were observed on live hardware or the host, **Nominal** facts come from
manufacturer documentation and were not independently measured,
**Documented** facts come from the restricted Alex003 guide and were not
live-verified, and **Planned** items were selected but have not been acquired,
installed, or validated. Where the canonical source assigns no glossary label
to an unknown or approximate record, this closeout says so instead of inferring
one.

## Proposed bench and inventory mapping

The temporary pilot path permits MacBook speakers as the source. The ReSpeaker
XVF3800 is the current capture device; in the proposed bench it connects by USB
to the Raspberry Pi 5, but that move and its required tests remain pending under
Gate 2. The Raspberry Pi and workstation use the same wired Purdue subnet. The
ZED 2i connects directly to the workstation over USB 3. The current, not-frozen
reference-output purchase direction replaces the MacBook source with one
Genelec 8030C powered monitor driven through a Focusrite Scarlett Solo USB
interface. That planned output interface is separate from the ReSpeaker USB
audio interface and microphone array.

| Required field | Current state | Canonical evidence label | Missing, unknown, or unmeasured |
| --- | --- | --- | --- |
| Raspberry Pi | Raspberry Pi 5 with 8 GB RAM, official black case, official 27 W USB-C supply, and an available SanDisk Extreme 128 GB microSD. The verified host is Debian GNU/Linux 13 (`trixie`), ARM64, kernel `6.18.34+rpt-rpi-2712`, with key-only SSH through `elab-raspberrypi5`; it and the workstation are on the same wired Purdue subnet. | **Verified** | The ReSpeaker has not yet been moved to the Pi for the required capture, playback, disconnect, and long-run tests. Final serial numbers and software/firmware versions are not frozen. |
| Audio interface | The ReSpeaker XVF3800 is the current USB audio interface and microphone array. It is detected as a USB Audio device at USB 2 speed; the live interface currently exposes two channels at 16 kHz using `S16_LE`. A Focusrite Scarlett Solo is **Planned** as a separate USB interface for the reference-monitor output path. | **Verified** for the current ReSpeaker USB device and live format; **Planned** for the Focusrite Scarlett Solo | The official six-channel ReSpeaker firmware still requires flashing, hashing, and post-flash ALSA verification. The firmware version, binary hash, formats, and playback behavior are not recorded. The Scarlett Solo has not been acquired, installed, or validated; its cable path must be revalidated, and the purchase BOM is not frozen. |
| Microphone count | The ReSpeaker is a four-microphone circular array. The target official six-channel USB firmware would expose two processed channels plus four raw microphone channels; the live interface currently exposes only two channels. | **Verified** for the physical four-microphone array and current two-channel exposure; the six-channel firmware is a target, not verified live state | Four raw microphone channels have not yet been exposed and verified after the firmware change. |
| Microphone geometry | Manufacturer-listed microphone spacing is 66 mm. | **Nominal** for the 66 mm spacing; all other geometry remains unknown | The 66 mm value has not been independently measured. Exact microphone coordinates, acoustic centers, array axes, and enclosure-based geometry are not measured. |
| Channel order | No microphone channel order is established. The current live interface exposes two channels, but that fact does not identify their physical order. | **Verified** only for the two-channel exposure; no canonical evidence label applies to the unknown channel order | Channel identity and order, polarity, per-channel delay, and gain remain unmeasured. They must be verified after the six-channel firmware is installed. |
| Speaker | The **Verified/limited** pilot source is the user's MacBook built-in speakers. The **Planned**, current-but-not-frozen reference direction is one Genelec 8030C powered monitor driven through a Focusrite Scarlett Solo USB interface, superseding the prior Genelec 8010A direction. | **Verified** for the limited temporary MacBook source; **Planned** for the Genelec 8030C and Focusrite Scarlett Solo path | The exact MacBook model is unknown. Pilot takes must record the specified output, software, level, power, pose, distance, and processing controls. The planned reference path has not been acquired or characterized, the Hosa cable choice must be revalidated against it, and the purchase BOM is not frozen. |
| Camera and software | A Stereolabs ZED 2i is connected directly to the workstation at USB 3, 5 Gb/s; the existing cable is adequate. The ZED SDK was not installed at audit time. | **Verified** for the camera and connection; **Planned** for the ZED software installation | Install and validate the current official Ubuntu 24/CUDA 12 ZED SDK build and record its hash/version. Update camera firmware only if the official ZED tool offers it; no update is claimed. The ZED/ReSpeaker extrinsic transform is unmeasured. |
| Mounts | No dedicated tripod, speaker stand, or rigid ZED/ReSpeaker mount is currently available. Two K&M 201A/2 stands are selected for the reference speaker and UMIK-1. The bench and Alex configuration require a rigid, removable ZED/ReSpeaker bar with a measured transform and standard tripod interface. | **Planned** for the selected stands; the canonical source assigns no glossary label to the required bar or the current absence | The enclosures, mount geometry, and ZED/ReSpeaker transform have not been measured. The tripod and final bracket BOM remain unselected pending enclosure measurements. Alex mounting authorization and an approved USB route remain unknown. |
| Room | The meeting-room reference environment is Purdue University WANG 2052. The current record gives approximate dimensions of 6.5 m x 3.0 m x 3.0 m and approximate derived volume of 58.5 m3, carpet tiles, a suspended acoustic-tile ceiling with lighting and HVAC openings, painted walls, whiteboards, a mounted display, glass, a hard fixed table, 13 movable chairs, and two movable waste bins. | The canonical source assigns no glossary label to this current room record; the approximate dimensions are not treated as Verified or measured | Measure the room and fixed-object geometry. Exact floor, ceiling, and surface construction/absorption are unknown. Each accepted take must record door and HVAC state, furniture layout, source and sensor heights, temperature, humidity, and people present. |
| Clocks and synchronization | Wired Raspberry Pi/workstation reachability is **Verified**, but the canonical source explicitly says that wired reachability does not prove clock synchronization. | **Verified** for wired network reachability only; no canonical evidence label applies to synchronization, which remains unlocked | Select and lock a chrony/NTP or PTP policy, offset logging, acquisition metadata, and a synchronization failure threshold. No synchronized-calibration claim is supported. |
| Measurement tools | No calibrated microphone, environmental meter, turntable, laser distance meter, angle gauge/level, digital caliper, or dedicated metric tape is currently available. Planned equipment is one serial-calibrated miniDSP UMIK-1, Bosch GLM165-25G laser distance meter, Klein Tools 935DAG digital angle gauge/level, iGaging 100-700-06 digital caliper, Komelon 4916IM tape, and Testo 608-H1 temperature/humidity meter. | **Planned** for the selected UMIK-1 and measurement tools; the canonical source assigns no glossary label to their current absence | Acquire and characterize the selected tools before S4. A traceable Class 2 meter/calibrator remains a later decision only if required by the final claim; a turntable is deferred pending pilot evidence. Tool serial numbers, calibrated profiles, and the final BOM are not frozen. |

No **Documented** Alex-guide fact is used to fill an unknown bench measurement.
The guide's limited hardware context remains separated in the canonical source,
and no credential or restricted guide content is reproduced here.

## Pending gates

The following list mirrors the canonical source's
[`Remaining Gates`](../../../reference_rig_hardware_environment.md#remaining-gates).
None is marked passed:

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

The purchase BOM is explicitly still open. In particular, the Genelec 8030C
plus Focusrite Scarlett Solo direction is current but not frozen, and the
previously selected Hosa CYX-403M cable must be revalidated against that path.
This open decision does not pass or replace Gate 8.

## Acceptance check

The S0.5 inventory stop condition is met as an inventory record: the current
pilot bench, planned reference-output path, network topology, camera path,
environment, and selected mounting/measurement equipment are identified, while
each unavailable item, unknown identity, missing software state, unverified
channel property, unlocked clock policy, and unmeasured physical quantity is
called out in the mapping and pending gates. A reviewer can therefore
reconstruct the proposed bench or identify every missing item without treating
the proposed bench as calibrated.

No estimated or nominal geometry is labeled measured. In particular, the
manufacturer-listed 66 mm ReSpeaker spacing remains **Nominal**, and the room's
approximate dimensions remain an unlabeled current record pending measurement.
Exact microphone coordinates, channel order, array axes, acoustic centers,
extrinsics, mount geometry, room geometry, source poses, and uncertainty remain
explicitly unknown or unmeasured.

## Boundary and follow-on gate

This closeout is an inventory record, not calibration evidence. S4 owns physical
measurement, channel and frame lock, clock policy, acquisition controls,
calibration, uncertainty, and calibrated sim-vs-real evidence. Until the
pending gates pass, the canonical description remains an available
four-microphone development rig, not a calibrated research reference.
