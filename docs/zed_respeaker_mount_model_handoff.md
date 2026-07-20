# ZED 2i / ReSpeaker Future 3D-Printed Mount — Model and Development Handoff

Last updated: 2026-07-20

Design: `ZED_ReSpeaker_Mount_RevA`

Current decision: `OPTION_1_F3_STANDARD_SEATING`

Repository note: paths to `releases/`, `parameters/`, `drawings/`, `evidence/`,
and `fusion/` below are relative to the companion CAD project and release
archive. Those CAD artifacts are not stored in this package repository.

## Read this first

Revision A Option 1 is reported **digitally complete and released**. The clean
saved Fusion source is reported as cloud version 9, and the intended
authoritative release package is
[`releases/ZED_ReSpeaker_Mount_RevA_2026-07-18_Option1/`](releases/ZED_ReSpeaker_Mount_RevA_2026-07-18_Option1/).
That companion release and its exact nominal-transform JSON were not
retrievable from this repository, the current workstation search, or connected
Drive during S4.1 closeout. The files are not reconstructed from prose.

This design was not printed or installed for S4.1. The passing S4.1 authority
is the separate handmade `S4_TEMP_DESKTOP_FIXTURE_REV0`; therefore missing
future-design files do not block that fixture's closeout. When this design is
eventually printed, it must receive a new mount identity, new as-built pose and
uncertainty measurements, and new practical fixture checks before use.

The assembly is **not yet physically or field accepted**. The real build must
still pass the controlled tests in
[`option1_physical_acceptance_test_record.md`](evidence/option1_physical_acceptance_test_record.md).
Cable-clamp shims must also remain measurement-pending until both real cable
jacket diameters are measured at their intended clamp locations.

This file is the compact future-design handoff. Numerical values here summarize
reported companion-project files and must not be assigned to the handmade S4.1
fixture. When the source becomes available for editing or release, use the
linked machine-readable specification, drawings, BOM, and evidence as its
source of truth.

## 1. Purpose and design boundary

The model is a rigid, serviceable mount for:

- one USB-C Stereolabs ZED 2i, serial `39011785`;
- one enclosed ReSpeaker XVF3800, SKU `114993701`;
- their first cable captures;
- a detachable table-mode base with steel ballast and six adhesive feet;
- a keyed four-M3 platform interface and a metal 1/4-20 insert.

The common carrier fixes the relative sensor geometry. The table base is a
replaceable adapter: future platform variants must not move either sensor or
its first cable capture.

The model is not a calibrated optical/acoustic extrinsic. The nominal transform
is mechanical only; final sensor calibration and uncertainty must be measured
on the assembled system.

## 2. Coordinate system and locked sensor geometry

- Fusion `+X`: project right.
- Fusion `-Y`: project forward; Fusion `+Y` is project rear.
- Fusion `+Z`: up.
- ZED mechanical center: `[0, 0, 80] mm`.
- ReSpeaker mechanical center: `[0, 0, 170] mm`.
- Center separation: `90 mm`, locked within the approved `80–110 mm` range.
- ReSpeaker reference: rotated `180°` about Z and recentered by Fusion
  `x = 0.349379907 mm`.
- Intended nominal-transform source:
  `parameters/T_zed_from_array_nominal.json` in the unavailable companion
  release. Do not reconstruct that file from the prose values in this handoff.

Do not change these transforms without a new design decision, a new release,
and a new as-built calibration.

## 3. Mechanical architecture

### ZED interface

- Uses the two official bottom M3 × 0.5 threads.
- Retained by two M3 × 12 socket-head screws and 0.5 mm washers.
- A positive underside key permits the correct pose and blocks a 180° reversed
  camera: validated interference is `0 mm³` correct and `226.655907 mm³`
  reversed.
- The camera screws are serviced after removing the four shelf M4 screws; this
  is intentional for tool access.

### ReSpeaker interface

- The enclosure rests on its three factory feet in pockets with `0.60 mm`
  clearance per side.
- Two removable ring halves, retained by four M3 × 10 screws, prevent lift.
- No sensor drilling or adhesive is permitted.
- Microphone openings, controls, 3.5 mm jack, and active XMOS USB-C area remain
  accessible.
- Install with the XMOS USB-C toward project rear, Fusion `+Y`.

### Carrier, platform, and cables

- Shelf and cradle use eight M4 × 16 screws into RX-M4x8.1 inserts.
- Carrier-to-platform uses four M3 × 25 screws on the keyed `50 × 35 mm`
  interface into RX-M3x5.7 inserts.
- The carrier includes one RX-1/4-20x12.7 insert with an `8.0 mm` pilot.
- Cable clamps are centered at Fusion `x = ±18`, `y = 129`, `z = 28 mm`.
- Both cables remain straight through their plug/service envelopes, then route
  independently rearward/down.
- Cables must never locate or preload either sensor.

## 4. Released parts and fabrication files

All eight printable components exist in validated **3MF and STL**, with STEP
also provided:

| Printable component | Nominal print envelope (mm) | Main role |
|---|---:|---|
| `Table_Base` | `200 × 190 × 24` | Table adapter, feet, ballast interface |
| `Sensor_Carrier` | `100 × 139 × 137` | Common sensor/cable structure |
| `ZED_Attachment` | `160 × 61 × 29.25` | Keyed camera shelf |
| `ReSpeaker_Cradle` | `134 × 91.093008 × 17` | Three-foot array support |
| `ReSpeaker_Ring_Left` | `66.5 × 123.327640 × 20.1` | Removable retention half |
| `ReSpeaker_Ring_Right` | `66.5 × 123.327640 × 20.1` | Removable retention half |
| `Cable_Clamp_Left_Cap` | `26 × 8 × 20` | Left split-clamp cap |
| `Cable_Clamp_Right_Cap` | `26 × 8 × 20` | Right split-clamp cap |

Use the release [`3mf/`](releases/ZED_ReSpeaker_Mount_RevA_2026-07-18_Option1/3mf/)
files by preference because their millimeter units are explicit. The release
[`stl/`](releases/ZED_ReSpeaker_Mount_RevA_2026-07-18_Option1/stl/) files are
binary, millimeter-scale, and topology-validated. Purchased screws, inserts,
feet, sensors, and cables do not require STL models. The fabricated steel
ballast is supplied separately as STEP and DXF under release `hardware/`.

Print the base, carrier, sensor attachments, cradle, and ring halves with
assembly `+Z` upward and the lowest face on the bed. Rotate each cable-clamp cap
`90°` about X and print it on its Y end face. The carrier bridges, elevated
cradle network, and ring lips may need localized support.

Start with PLA for fit checks. Use PETG or ASA for the functional build after
fit acceptance, with at least three perimeters, `30–40%` infill, and local
reinforcement at inserts and adapter joints. Every part fits a
`220 × 220 × 200 mm` printer; the base also fits with a 4 mm brim.

## 5. Option 1 table-base specification

### Steel ballast

- ASTM A36 hot-rolled flat bar, stock `3/16 × 5 × 5-1/4 in`.
- Finished nominal envelope: `127.0 × 133.35 × 4.7625 mm`.
- Permitted thickness: `4.3815–5.1435 mm`.
- Center: Fusion `(0, 30, 0)`; top interface at `z = 0`, plate below it.
- Minimum finished mass: `0.550 kg`.
- Calculated mass: `0.631094853 kg` nominal and `0.580370590 kg` at minimum
  permitted thickness.
- Four hole centers, plate-local: `x = ±50`, `y = ±40 mm`; Fusion-global:
  `x = ±50`, `y = -10, 70 mm`.

### Countersinks and screws

- Countersink: standard DIN 74:2020 Form F3, not manufacturer-customized.
- Through hole: Ø`3.4 H13`, limits `3.400–3.580 mm`.
- Major diameter: Ø`6.9 H13`, limits `6.900–7.120 mm`.
- Included angle: `90°`; nominal geometric depth `1.75 mm` from the
  table-facing steel surface.
- Screws: four ISO 10642:2026 M3 × 0.5 × 10, fully threaded, length measured
  over the complete head-to-tip.
- Screw envelope: length `9.71–10.29 mm`, head Ø`5.54–6.72 mm`, head height
  `1.52–1.86 mm`, head angle `90–92°`, HS2, steel 10.9/010.9, zinc plated.
- No washer. The head must never be proud; `0–0.8 mm` recession is accepted.
- Controlled geometric recession envelope: `0.0869119897–0.7900000000 mm`.
- Representative part: Würth `008903 10`, EAN `4011231155366`. BelMetric
  `SF3X10CLZ` is acceptable only after lot-specific dimensional verification.

### Insert pocket and complete tolerance stack

- Insert: exact Ruthex RX-M3x5.7; `4.0 mm` pilot.
- Blind pocket depth: `8.0 mm`.
- Local reinforcement: Ø`12 × 2.0 mm` boss, giving `10.0 mm` total local
  printed thickness, `2.0 mm` roof, and `3.7 mm` nominal radial material
  outside the insert envelope.
- Stack equation: `q = L + r - t - g`, with controlled design gap `g = 0`.
- Minimum geometric insert overlap: `4.5665 mm`.
- Minimum complete-thread engagement after two incomplete tip threads:
  `3.5665 mm`.
- Maximum penetration below the plate/insert interface: `6.7085 mm`.
- Maximum extension beyond the insert: `1.0085 mm`.
- Minimum pocket-to-tip clearance: `1.2915 mm`.

The stack therefore prevents bottoming across the controlled envelopes while
retaining more than the required `1.0 mm` worst-case tip clearance. Future
changes must recompute the complete tolerance stack; nominal-only checks are
not sufficient.

### Feet and table clearance

- Six exact 3M Bumpon `SJ5027 BLACK`, 3M ID `7000001887`.
- Nominal size `16.00 × 7.93 mm`, published tolerance `±0.5 mm`, R30 adhesive,
  72 Shore M lot evidence required.
- Recesses: Ø`17.2 × 1.0 mm`.
- Centers: Fusion `x = ±85`, `y = -50, 30, 110 mm`.
- Uncompressed ballast-to-table clearance: `2.1675 mm` nominal and
  `1.2865 mm` worst geometric value.
- Screw heads and the ballast plate must never become table-contact elements.

## 6. Controlled hardware summary

| Joint | Hardware |
|---|---|
| ZED to shelf | 2 × M3 × 12 socket head; 2 × 0.5 mm M3 washers |
| Shelf/cradle to carrier | 8 × M4 × 16; 8 × RX-M4x8.1, 5.6 mm pilots |
| Carrier to table adapter | 4 × M3 × 25; 4 × RX-M3x5.7, 4.0 mm pilots |
| ReSpeaker rings | 4 × M3 × 10; 4 × RX-M3x5.7 |
| Cable-clamp caps | 4 × M3 × 10; 4 × RX-M3x5.7 |
| Ballast | 4 × ISO 10642 M3 × 10; 4 × RX-M3x5.7; no washers |
| Six feet | 6 × exact SJ5027 BLACK |
| Platform/photo interface | 1 × RX-1/4-20x12.7, 8.0 mm pilot |
| Cable shims | 2 × measured split TPU/EPDM; dimensions pending |

The exact procurement record is [`BOM.csv`](parameters/BOM.csv).

## 7. Assembly sequence

1. Print same-process insert coupons and qualify heat-setting and torque.
2. Install the ZED on the detached keyed shelf with two M3 × 12 screws and
   washers.
3. Rear-bolt the populated shelf and empty cradle to the carrier with eight
   M4 × 16 screws.
4. Attach the carrier to the keyed table adapter with four M3 × 25 screws.
5. Clean the six foot lands, install the exact feet with pressure and 72-hour
   dwell, heat-set the four ballast inserts, then fasten the inspected A36
   plate with the four ISO 10642 M3 × 10 screws. Record every screw stack and
   head recession.
6. Seat the ReSpeaker on its factory feet and install both ring halves.
7. Connect and route the cables through their service zones; add only measured
   cable shims and install the clamp caps last.

## 8. What has been validated digitally

- Fusion cloud version 9 was saved clean with the Option 1 cutover.
- The master contains the official sensor references and ten current rigid
  assembly relationships; the obsolete carrier-to-old-base relationship is
  absent and only the current table base is grounded.
- `computeAll` preserves the intended transforms and source fingerprint.
- 81 controlled interference checks found no unexpected volume.
- The printable assembly STEP round-trip returns eight named solids and no
  sheets or pairwise overlap; the complete assembly returns 104 solids and
  five reference sheets.
- Eight STL plus eight 3MF meshes passed topology, winding, scale, and checksum
  validation.
- Forty numerical assertions, sixteen exporter regression tests, and eight
  converter tests passed.
- The sealed release manifest contains 55 entries; the release directory has
  56 files including `SHA256SUMS`.

This proves the digital release package, not real-world fit, material quality,
adhesion, stiffness, stability, or calibration.

## 9. Physical release gates still pending

Record results in
[`option1_physical_acceptance_test_record.md`](evidence/option1_physical_acceptance_test_record.md).
The key objective criteria are:

- inspected A36 material, envelope, thickness, hole geometry, and finished
  mass `≥ 0.550 kg`;
- every screw head recessed `0–0.8 mm`, complete-thread engagement
  `≥ 3.5665 mm`, tip clearance `≥ 1.0 mm`, and no bottoming or damage;
- at least five same-process insert coupons; assembly torque equal to 50% of
  the lowest first-failure torque, capped by the fastener limit and
  `≥ 0.25 N·m`;
- production proof torque `1.25 ×` assembly torque for 5 seconds;
- 25 removal/reinstallation cycles, with final insert movement `≤ 0.2 mm`,
  rotation `≤ 2°`, and cycle-25 breakaway torque `≥ 80%` of cycle 1;
- after 72-hour foot dwell, contact at all six feet and rocking `≤ 0.25 mm`
  under alternating 5 N edge loads;
- after 24-hour loaded dwell, maximum foot compression `≤ 1.0 mm`, compression
  spread `≤ 0.5 mm`, and plate/head clearance `≥ 0.5 mm`;
- foot adhesion at 6 N for 60 seconds: slip `≤ 0.5 mm`, edge lift `≤ 0.5 mm`,
  and no peel or detachment;
- as-built anti-tip safety factor `≥ 1.5` for a 12 N pull in every direction;
- 18 N proof pull for 60 seconds, three repetitions in each of four directions:
  sliding `≤ 2.0 mm`, foot shift `≤ 0.5 mm`, and no lift, overturn, or peel.

## 10. Known unknowns and measurement holds

- Measure both real cable jacket diameters at the intended clamp locations
  before defining cable-shim dimensions. Do not copy a nominal cable diameter
  from a catalog or standardize one shim for both cables without evidence.
- Verify actual connector moldings, cable bend behavior, and strain relief.
- Verify insert fit, torque, service life, printed deflection, and ring service
  force on real parts.
- Confirm the authoritative ReSpeaker microphone channel-to-inlet mapping.
- Determine the ZED SDK optical frame relative to the mechanical reference.
- Measure the final assembled sensor extrinsic and its uncertainty.

## 11. Sources of truth

| Need | Authoritative file |
|---|---|
| Current editable design | Fusion project `isaac-audio-sensors`, design `ZED_ReSpeaker_Mount_RevA`, clean cloud v9 |
| Archived Option 1 source | [`ZED_ReSpeaker_Mount_RevA_Option1.f3d`](releases/ZED_ReSpeaker_Mount_RevA_2026-07-18_Option1/fusion/ZED_ReSpeaker_Mount_RevA_Option1.f3d) |
| Immutable pre-cutover backup | [`ZED_ReSpeaker_Mount_RevA_pre_ballast_foot_fastener_substitution_v6_20260718.f3d`](fusion/backups/ZED_ReSpeaker_Mount_RevA_pre_ballast_foot_fastener_substitution_v6_20260718.f3d) |
| Full model overview | [`README.md`](README.md) |
| Core constraints | [`revision_a_parameters.json`](parameters/revision_a_parameters.json) |
| Option 1 stack/specification | [`ballast_foot_fastener_substitution.json`](parameters/ballast_foot_fastener_substitution.json) |
| Hardware and quantities | [`BOM.csv`](parameters/BOM.csv) |
| Geometry and assembly | [`assembly_dimensions.md`](drawings/assembly_dimensions.md) |
| Digital validation | [`revision_a_validation.json`](evidence/revision_a_validation.json) and [`ballast_substitution_export_audit.json`](releases/ZED_ReSpeaker_Mount_RevA_2026-07-18_Option1/evidence/ballast_substitution_export_audit.json) |
| Physical qualification | [`option1_physical_acceptance_test_record.md`](evidence/option1_physical_acceptance_test_record.md) |
| Fabrication package | [`ZED_ReSpeaker_Mount_RevA_2026-07-18_Option1`](releases/ZED_ReSpeaker_Mount_RevA_2026-07-18_Option1/) and its [`SHA256SUMS`](releases/ZED_ReSpeaker_Mount_RevA_2026-07-18_Option1/SHA256SUMS) |

Release identity:

- Fusion migration ID: `ea316358-5395-42f7-b98d-df682eecb51a`.
- Immutable backup SHA-256:
  `8c2db1db2bea54a1eaf75807ddf430d0d955b82e4b1febd788cc578b2d8f297a`.
- Option 1 F3D SHA-256:
  `ab9c5443e1b6aed3c550653927ae2e863afd6dcfd9fa5af17bfc187c5c1ed1f4`.
- Export-audit SHA-256:
  `907760ec0343529f7d65f5bb410d97792520dec9a0bf032e09cc33c15f2b0b54`.
- Manifest SHA-256:
  `e7893bd043398468e6f0342b42b9ac502c1fef5ac0e54d4c5d2dce9b7bb93ee7`.

The cloud-v6 release
[`ZED_ReSpeaker_Mount_RevA_2026-07-17`](releases/ZED_ReSpeaker_Mount_RevA_2026-07-17/)
is superseded. Directories marked `.failed` are forensic export attempts and
must never be used for fabrication. Do not modify the read-only Option 1
release or the immutable v6 backup.
