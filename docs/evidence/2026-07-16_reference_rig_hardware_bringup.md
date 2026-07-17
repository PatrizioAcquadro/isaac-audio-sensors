# Reference Rig Hardware Bring-Up — 2026-07-16

This report records the standalone official hardware bring-up for the Isaac
Audio Sensor and SquadBot reference rig. It did not execute roadmap phase S0 or
change any roadmap phase status. Only official Seeed Studio/ReSpeaker and
Stereolabs sources and manufacturer-provided artifacts were used.

## ReSpeaker XVF3800

### Provenance and firmware

- USB identity: `2886:001a`
- Device serial: `114993701261100454`
- Pre-upgrade firmware: `2.0.6`
- Pre-upgrade native capture: two channels, 16 kHz, `S16_LE`
- Repository: `https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY`
- Commit: `e4c2073e1470180746580a6ba5468c9bf45026e1`
- Binary: `xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_6chl_v2.0.8.bin`
- Binary SHA-256: `8dd27762ebd87a28f0b4546f1634ece5e7eae308375d66952f7a9e3fb948266a`
- `dfu-util`: Ubuntu package `0.11-1`
- DFU target: alternate 1, `reSpeaker DFU Upgrade`
- Command:

  ```text
  sudo dfu-util -R -e -a 1 -D respeaker_xvf3800_usb_dfu_firmware_6chl_v2.0.8.bin
  ```

The cable was attached to the XMOS USB-C port beside the 3.5 mm jack. DFU
alternate 0, `reSpeaker DFU Factory`, was identified but never written. The
flash transferred 933,888 bytes, completed manifest status 0, and reset the
runtime. The device was physically power-cycled afterward.

### Post-upgrade control reads

- Firmware: `2.0.8`
- `AEC_MIC_ARRAY_GEO`: `(0.033, -0.033, 0)`, `(0.033, 0.033, 0)`,
  `(-0.033, 0.033, 0)`, `(-0.033, -0.033, 0)` m
- Live `DOA_VALUE` reads succeeded (`[100, 0]` after the workstation flash;
  an earlier pre-upgrade read was `[97, 0]`)
- No algorithm parameter was tuned or overwritten.

The official six-channel documentation describes 32-bit samples, but the live
post-upgrade USB descriptor reports a two-byte audio subslot. Direct ALSA
hardware probing on both hosts exposes only six-channel, 16 kHz `S16_LE`;
`S32_LE` is rejected. The verified hardware format is therefore `S16_LE`.

Official channel map:

| Channel | Signal |
| --- | --- |
| 0 | Conference |
| 1 | ASR |
| 2 | Raw microphone 0 |
| 3 | Raw microphone 1 |
| 4 | Raw microphone 2 |
| 5 | Raw microphone 3 |

### Workstation validation

The ten-second WAV was created outside Git at
`/tmp/respeaker_workstation_6ch_20260716.wav`:

- PCM `S16_LE`, 16 kHz, six channels, 1,920,044 bytes
- SHA-256: `71ac9ee4530dbcdfe1efee610c674008051b756533baedc2943be2475897176e`

| Channel | RMS | Absolute peak | Full-scale samples |
| --- | ---: | ---: | ---: |
| 0 | 384.294 | 32768 | 1 |
| 1 | 214.078 | 11437 | 0 |
| 2 | 161.249 | 4558 | 0 |
| 3 | 165.308 | 4232 | 0 |
| 4 | 185.153 | 9362 | 0 |
| 5 | 179.571 | 7695 | 0 |

All channels were non-silent. Raw microphone pairs were not sample-identical;
pairwise correlations ranged from 0.797701 to 0.943040. The single negative
full-scale sample on channel 0 is recorded explicitly; there was no sustained
clipping or malformed WAV structure. Native two-channel playback streaming at
16 kHz `S16_LE` completed successfully, but audible 3.5 mm output was not
physically confirmed.

### Raspberry Pi validation

- Host: `elab-raspberrypi5`
- OS: Debian GNU/Linux 13 (`trixie`), ARM64
- Kernel: `6.18.34+rpt-rpi-2712`
- Same ReSpeaker serial and firmware; six-channel capture and two-channel
  playback enumerated at 16 kHz `S16_LE`
- No additional packages were required or installed.

The ten-second Pi WAV was created outside Git at
`/tmp/respeaker_pi_6ch_20260716.wav`:

- PCM `S16_LE`, 16 kHz, six channels, 1,920,044 bytes
- SHA-256: `b05af9222df3d89f342549d4049686e2cf03e6d46170267ffaed642fb0c815b2`

| Channel | RMS | Absolute peak | Full-scale samples |
| --- | ---: | ---: | ---: |
| 0 | 124.891 | 825 | 0 |
| 1 | 216.658 | 1161 | 0 |
| 2 | 181.089 | 772 | 0 |
| 3 | 187.423 | 798 | 0 |
| 4 | 195.727 | 879 | 0 |
| 5 | 193.162 | 864 | 0 |

All channels were non-silent. Raw microphone pairs were not sample-identical;
pairwise correlations ranged from 0.977977 to 0.993760. There was no clipping
or malformed WAV structure. Native playback streaming completed successfully;
audible output was not physically confirmed. A physical disconnect/reconnect
changed the USB device number and recovered capture/playback enumeration. A
post-reconnect two-second capture passed. A bounded 1,800-second six-channel
stream to `/dev/null` exited 0 without errors or a large artifact.

## ZED 2i and ZED SDK

### Preflight and installation

- Workstation: Ubuntu 24.04.4, RTX 4090, NVIDIA driver `580.159.03`
- Driver-reported CUDA generation: 13.0
- Installed CUDA toolkit: `12.2.140` at `/usr/local/cuda-12.2`
- Camera USB: `2b03:f880` video at 5 Gb/s and `2b03:f881` HID
- `/usr/local/zed` was absent before installation.
- Official release: ZED SDK `5.4.0`, June 18, 2026
- Installer URL: `https://download.stereolabs.com/zedsdk/5.4/cu12/ubuntu24`
- Installer: `ZED_SDK_Ubuntu24_cuda12.8_tensorrt10.9_v5.4.0.zstd.run`
- Installer size: 1,418,984,552 bytes
- Installer SHA-256: `bab3ae693865225b0e2cac2b09dadd0c520ce245a011a8e3785037ec46f1f811`

The official installer was run interactively with its normal path and no skip,
silent, runtime-only, or source-build options. It installed the full SDK,
tools, samples, Python support, TensorRT 10.9, and neural depth models. Existing
NVIDIA driver 580.159.03 and CUDA toolkit 12.2 were compatible and unchanged.
The requested reboot completed normally.

### Diagnostic and camera identity

`/usr/local/zed/tools/ZED_Diagnostic -c` exited 0. The original report was kept
outside Git; its SHA-256 is
`9f684bcf8474d4d886d94500579cd7b179224bb2e02d45dbe89faac7821a5f5b`.
The sanitized report is
[`2026-07-16_zed_diagnostic_sanitized.json`](2026-07-16_zed_diagnostic_sanitized.json).

Verified results:

- ZED SDK runtime and diagnostic version `5.4.0`
- CUDA operations passed on the RTX 4090
- ZED 2i and USB 3 bandwidth reported OK
- Neural Light, Neural, and Neural Plus depth models optimized
- Camera serial `39011785`
- Camera firmware `1523`; sensor firmware `777`
- Official SDK-bundled ZED 2i firmware is also `1523`; its local SHA-256 is
  `931fb6f47a8a01fc466114e0b33fa416bee36848b2010c49115bd872880a71e3`.
  No camera firmware update was required or performed.

The command-line diagnostic warned that it could not verify the OpenGL default
GPU because it had no graphical display context. The official graphical tools
subsequently started and worked, so this was not treated as a CUDA or camera
failure. No manual calibration was run because Diagnostic did not require it.

### Viewer, depth, IMU, and stability tests

The user visually confirmed that ZED Explorer, ZED Depth Viewer, and ZED Sensor
Viewer all start and work. The official SDK API independently verified ZED 2i
identity, USB 3, HD720 at 60 FPS, stable left/right images, neural depth, and
IMU reads.

The first bounded ten-minute run failed on the original direct USB port. The SDK
recovered the camera twice, and the kernel recorded UVC protocol error `-71`,
physical USB disconnects, and re-enumeration. That failed run completed
34,819 grabs but had a 9,893.024 ms image gap and is not counted as a pass.

After physically reseating the cable and selecting a different direct rear USB
3 port:

- 120.007-second precheck: 7,200 successful HD720@60 grabs, zero failures,
  121 left/right/depth retrieval checks, 121 successful sensor reads, maximum
  image gap 16.888 ms.
- 600.016-second acceptance test: 35,998 successful HD720@60 grabs, zero
  failures, 600 left/right/depth checks, 600 successful sensor reads, no reset
  or SDK recovery, maximum image gap 33.389 ms.

### SVO evidence

The short recording remains outside Git at
`/tmp/zed2i_bringup_20260716.svo2`:

- SVO version 2, H.264
- HD720 at 30 FPS
- 302 frames over 10.031 seconds
- 17,209,314 bytes
- SHA-256: `e0030e9217dd17471e71726681c0fd2c00c3f043b7e48dc8ec90725625c4ed2d`

## Result and Remaining Gates

Passed:

- Official ReSpeaker six-channel firmware installation and checksum
- Workstation and Raspberry Pi native six-channel capture
- Non-silent, non-identical raw microphones and valid WAV structure
- Raspberry disconnect/reconnect and bounded 30-minute streaming
- Full official ZED SDK installation without driver/CUDA migration
- Official ZED Diagnostic, Explorer, Depth Viewer, and Sensor Viewer
- Clean ZED left/right/depth/IMU precheck and ten-minute acceptance rerun
- Short checksummed SVO outside Git
- Camera firmware compatibility; no update required

Not passed or intentionally still open:

- Audible ReSpeaker playback through the physical 3.5 mm output was not
  confirmed, although native playback streaming succeeded on both hosts.
- Mounting, purchases, room and sensor geometry measurements, ZED/ReSpeaker
  extrinsics, clock synchronization, calibration, calibrated profiles, final
  BOM freeze, and Alex access/mounting authorization remain open.

## Official Sources

- https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/
- https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY
- https://www.stereolabs.com/docs/development/zed-sdk/linux
- https://www.stereolabs.com/developers/release/
