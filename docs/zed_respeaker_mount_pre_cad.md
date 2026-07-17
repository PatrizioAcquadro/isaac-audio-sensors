# ZED 2i And ReSpeaker Rigid Mount: Pre-CAD Input Lock

Status: **CAD Revision A input lock; sensor carrier and table base approved to model**

Last updated: **July 17, 2026**

This document records the mechanical and coordinate-frame inputs for a rigid,
removable ZED 2i/ReSpeaker reference rig. It separates live-verified hardware
identity, user-confirmed physical facts, manufacturer-nominal geometry, values
derived from manufacturer CAD, and measurements that can only be made after the
mount is fabricated.

The document is an input to CAD design and later S4.1 frame lock. It is not a
calibrated extrinsic measurement.

## Evidence Terms

- **Verified:** observed on the live device or host during the July 16, 2026
  bring-up.
- **User-confirmed:** physically identified by the owner on the available unit.
- **Nominal:** published by the manufacturer and not independently measured on
  this unit.
- **CAD-derived:** calculated from manufacturer-provided STEP geometry.
- **Photo-derived:** inferred conservatively from owner-supplied photographs and
  known device geometry; suitable for a clearance envelope, not metrology.
- **Proposed:** a design choice that remains subject to approval before CAD.
- **Locked:** approved as an input to CAD Revision A.
- **As-built:** measurable only after the physical mount has been fabricated and
  assembled.

## Exact Hardware In Scope

### Stereolabs ZED 2i

| Fact | Value | Status |
| --- | --- | --- |
| Model | Stereolabs ZED 2i | Verified |
| Serial | `39011785` | Verified |
| Camera firmware | `1523` | Verified |
| Sensor firmware | `777` | Verified |
| Host interface | Rear USB-C connector; direct USB 3 connection to the workstation | User-confirmed and verified |
| Excluded connector family | This is not a ZED X/ZED X Mini GMSL camera; do not use ZED X mechanical or cable geometry | User-confirmed |
| Overall enclosure | `175.3 x 30.3 x 43.1 mm` | Nominal |
| Stereo baseline | `120 mm` | Nominal |
| Weight | `229 g` | Nominal |
| Side mounting threads | Two `M3 x 0.5` holes; manufacturer drawing gives `10 mm` maximum screw length | Nominal |
| Bottom mounting thread | One `1/4-20 UNC` hole; manufacturer drawing gives `7 mm` maximum screw length | Nominal |
| Cable in use | Approximately `0.5 m`, non-original USB-C-to-USB-C cable with straight molded plugs | User-confirmed and photo-derived |

The external USB-C plug, strain relief, and cable bend envelope are not included
in the enclosure dimensions. The exact cable used on the rig must therefore be
included in the final clearance check.

Official sources:

- [ZED 2i product and CAD-download page](https://store.stereolabs.com/products/zed-2i)
- [ZED 2i datasheet and technical drawing](https://support.stereolabs.com/hc/en-us/article_attachments/27901419901463)

### Seeed Studio ReSpeaker XVF3800

| Fact | Value | Status |
| --- | --- | --- |
| Product | ReSpeaker XVF3800 USB 4-Mic Array with case, without XIAO | Verified |
| Manufacturer SKU | `114993701` | Verified from the device identity and official product variant |
| Serial | `114993701261100454` | Verified |
| Firmware | Official six-channel USB firmware `2.0.8` | Verified |
| Native capture | Six channels, `16 kHz`, `S16_LE` | Verified |
| Host connector | USB-C on the enclosure perimeter | Verified |
| Bare-board envelope | Approximately `99 mm` diameter and `4 mm` PCB thickness | Nominal |
| Enclosed-unit envelope | Approximately `108.7 x 108.0 x 18.4 mm` | CAD-derived |
| Cable in use | Official supplied USB-A-to-USB-C data cable with a straight molded USB-C device plug | User-confirmed and photo-derived |

The enclosed-unit envelope was calculated from the manufacturer-provided upper
and lower enclosure STEP files. The value includes the modeled exterior rather
than treating the bare-board `99 mm x 4 mm` annotation as the enclosure size.
The final CAD system must import both STEP files and recompute the assembly
bounding box rather than relying only on the rounded values above.

Official sources:

- [ReSpeaker XVF3800 with case, SKU 114993701](https://www.seeedstudio.com/ReSpeaker-XVF3800-USB-4-Mic-Array-With-Case-p-6490.html)
- [ReSpeaker XVF3800 hardware and operating guide](https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/)
- [Upper enclosure STEP](https://files.seeedstudio.com/wiki/respeaker_xvf3800_usb/3d/1-up.stp)
- [Lower enclosure STEP](https://files.seeedstudio.com/wiki/respeaker_xvf3800_usb/3d/1-down.stp)

## ReSpeaker Microphone Geometry

The official control interface reports these configured microphone coordinates:

| Microphone | Nominal position `(x, y, z)` in meters |
| --- | --- |
| `mic_0` | `(0.033, -0.033, 0.000)` |
| `mic_1` | `(0.033, 0.033, 0.000)` |
| `mic_2` | `(-0.033, 0.033, 0.000)` |
| `mic_3` | `(-0.033, -0.033, 0.000)` |

These values define a nominal `66 mm` adjacent spacing. They are firmware
configuration values, not an as-built measurement of the acoustic centers.
The enclosure's four microphone inlets must remain fully exposed. The final
retention geometry must not use, cover, or load the inlet openings.

The physical mapping between `mic_0` through `mic_3`, the raw USB channels, and
the enclosure orientation remains an experimental verification item. It cannot
be inferred safely from the circular symmetry of the case alone.

## Coordinate Frames

The public project convention is:

- meters;
- local `+X` forward;
- local `+Y` right;
- local `+Z` up;
- positive bearing clockwise from `+X` toward `+Y`;
- quaternion serialization in `(x, y, z, w)` order.

The mount will eventually define:

- `F_rig`: a repeatable datum on the common mount;
- `F_zed`: the ZED SDK camera frame actually used by acquisition software,
  converted explicitly into the project convention;
- `F_array`: origin at the microphone-array center, with physically marked
  forward, right, and up axes.

The required transform direction is:

```text
p_zed = R_zed_from_array * p_array + t_zed_from_array
```

The final record must store `T_zed_from_array`, its inverse, translation in
meters, orientation as an `(x, y, z, w)` quaternion, and uncertainty.

## Locked Mechanical Architecture

CAD Revision A will use a common rigid sensor carrier plus replaceable platform
adapters:

1. use the ZED 2i's manufacturer-provided threaded mounts rather than clamping
   across the optical face;
2. retain the ReSpeaker case non-invasively in a locating cradle or split ring;
3. keep all four microphone inlets, buttons, USB-C, audio connectors, and the
   ZED field of view unobstructed;
4. use positive locating features so that each sensor has only one valid
   assembly orientation;
5. include cable strain relief without allowing the cables to determine sensor
   pose;
6. place a standard `1/4-20 UNC` interface on the common carrier or its bench
   adapter;
7. use a separate approved adapter for Alex instead of making the sensor
   carrier itself Alex-specific;
8. manufacture the carrier, ReSpeaker cradle, table base, and platform adapters
   as modular FDM-printed parts, with metal fasteners and threaded inserts at
   loaded or repeatedly serviced joints.

The ReSpeaker enclosure exposes a wall-hanging/keyhole feature, but its load
rating and remount repeatability are not documented. It must not be treated as
a precision robotic mounting interface without validation. A constrained
cradle is the safer current design direction.

The locked ReSpeaker restraint is a three-point locating cradle plus a removable
split retaining ring. The ring will use M3 fasteners and heat-set inserts. It
must retain the factory enclosure without drilling or adhesive and must leave
all microphone inlets, buttons, the 3.5 mm jack, and the active XMOS USB-C port
open.

## Locked Humanoid Layout

The desired layout prioritizes fidelity to a humanoid/Alex deployment while
remaining usable on a table:

- mount the ZED horizontally and facing forward at the nominal eye/forehead
  level of the rig;
- mount the ReSpeaker horizontally above the ZED in a crown-like position;
- align both sensor centers with the rig sagittal plane;
- align the marked project axes so both sensors use `+X` forward, `+Y` right,
  and `+Z` up after the ZED SDK frame conversion is applied;
- place the structural spine behind the ZED and keep the ReSpeaker center near
  the spine so the camera field of view is not obstructed and the overturning
  moment is limited;
- use approximately `90 mm` vertical center-to-center separation as the
  Revision A CAD target. The CAD may adjust this within `80-110 mm` to satisfy
  imported-geometry, field-of-view, connector, and stiffness checks. The exact
  final nominal transform must be exported from CAD.

This is a humanoid sensor placement, not a reproduction of human binaural
hearing. The ReSpeaker remains a four-microphone planar array.

## Cable Evidence And CAD Keep-Outs

Owner-supplied photographs from July 17, 2026 show straight molded USB-C plugs
at both devices. The ReSpeaker cable is the official supplied cable and exits
the active XMOS USB-C port beside the 3.5 mm jack. The ZED cable is non-original,
approximately `0.5 m` long, and has no screw-locking hardware. Neither cable
length is a dimensional driver for the carrier; the plug, strain relief, and
bend zone are.

No ruler was present in the photographs, so CAD Revision A must use conservative
clearance volumes rather than treating the following as measured plug sizes:

| Interface | Minimum open plug envelope from device surface | Additional bend/service zone | Status |
| --- | --- | --- | --- |
| ZED rear USB-C | `18 mm` wide x `14 mm` high x `40 mm` long | `30 mm` unobstructed behind the molded plug | Locked conservative CAD keep-out |
| ReSpeaker XMOS USB-C | `18 mm` wide x `14 mm` high x `35 mm` long | `25 mm` unobstructed beyond the molded plug | Locked conservative CAD keep-out |

The back of the carrier and the corresponding sector of the ReSpeaker cradle
must remain open. Each cable must leave the connector straight before being
captured by a separate strain-relief clip on the structural spine. The clip may
support the cable but must not locate either sensor. These envelopes must be
checked with the actual cables before the functional print is accepted; they
are deliberately oversized so a ruler measurement is not required before CAD.

## Alex Integration Evidence And Boundary

The supplied [Alex003 Usage Guide](https://docs.google.com/document/d/17QtexPK_RqmfRammA7CsvEUuhFZFkicrJfONCdlWkEg/edit)
was reviewed as a design reference. It states that the delivered head has an
enclosure location and routed GMSL cable for a possible **ZED X Mini** in the
chin, but that camera mounting hardware was not included. It instructs the user
to contact IHMC or design camera-specific hardware. That internal provision is
not directly compatible with the in-scope ZED 2i: the ZED 2i is a wider USB-C
camera and is not a ZED X Mini/GMSL device.

The guide identifies `alex_purdue.headTorso.urdf` on the provided Alex laptop as
the unit-specific model and names `HEAD_ZED_X_MINI_JOINT` as the nominal camera
frame. The public [IHMC Alex SDK](https://github.com/ihmcrobotics/ihmc-alex-sdk)
also provides Alex V2 head meshes and `alex_v2.head.urdf`. At inspected commit
`19abdc16dfc152d3394d92399f3eae6de85b9681`, that public URDF places the nominal
ZED X Mini frame relative to `HEAD_LINK` at:

```text
xyz = (0.11603, 0.009965, -0.02983) m
rpy = (0.0, 0.3633, 0.0) rad
```

The detailed Alex V2 head OBJ has a raw mesh-axis bounding box of approximately
`222.1 x 170.8 x 204.1 mm`; the URDF applies its own mesh rotation, so this raw
box is only an envelope check. These public V2 assets are useful for collision
and pose studies, but they have not been verified as the exact manufactured
Alex003 attachment geometry.

The common carrier must therefore expose a keyed, four-fastener adapter face.
CAD Revision A may model a provisional Alex envelope adapter against the public
mesh, but must not release an Alex mounting part for fabrication until one of
the following is available and approved:

- the unit-specific `alex_purdue.headTorso.urdf` plus the corresponding exact
  head CAD/mesh and intended external mounting surface;
- an IHMC-provided camera/sensor mounting part or drawing; or
- physical confirmation of the approved Alex003 fastener locations, spacing,
  accessible screw depth, cable path, and keep-out through full neck pitch and
  yaw.

This boundary does not block the sensor carrier or table-base CAD because the
Alex adapter is intentionally replaceable.

## Resolved Pre-CAD Decisions

| Item | Locked Revision A decision |
| --- | --- |
| Manufacturing | All structural and adapter parts are FDM printed. Use PLA for the fit prototype and PETG or ASA for the functional version. Use metal M3/M4 fasteners, washers, nuts, and heat-set inserts where appropriate. |
| Architecture | One rigid ZED-ReSpeaker carrier with replaceable table and Alex adapters. Changing the platform adapter must not change `T_zed_from_array`. |
| Layout | ZED front-facing; ReSpeaker horizontal above it; centered on the sagittal plane; nominal `90 mm` vertical center separation with the bounded CAD adjustment described above. |
| ReSpeaker retention | Three-point locating cradle plus removable split retaining ring; non-invasive and connector/microphone safe. |
| Cables | Use the photo-derived straight-plug evidence and the conservative keep-outs defined above. Provide open rear routing and independent strain relief. |
| Fabrication access | Design as modular parts for a common FDM build volume of at least approximately `220 x 220 x 200 mm`. Purdue BIDC is the preferred cross-major fabrication route; BoilerMAKER Lab is the backup. |
| Initial platform | A small freestanding printed table base with non-slip feet and a wide enough footprint to pass a cable-loaded tip-over check. No existing tripod, quick-release plate, clamp, or base must be matched. |
| Future interfaces | Include a metal `1/4-20 UNC` insert for optional photographic support and a keyed four-M3 adapter face for platform-specific parts. The exact Alex-side interface remains subject to the Alex boundary above. |

The table base is an initial test fixture, not the calibrated datum itself. It
must be detachable from the common carrier. CAD must size its footprint using
the final center of mass and a conservative pull from both connected cables;
rubber feet and optional table screw/clamp holes are allowed, but no external
tripod or clamp is required for Revision A.

Purdue fabrication references recorded for planning:

- [Bechtel Innovation Design Center](https://www.purdue.edu/bidc/faculty-resources/)
  as the first contact for cross-major project fabrication and material/process
  confirmation;
- [BoilerMAKER Lab](https://polytechnic.purdue.edu/facilities/boilermaker-lab)
  as an all-student FDM alternative;
- [Purdue 3D Printing Club](https://boilerlink.purdue.edu/organization/3DPC) as
  an additional support route.

No caliper or ruler measurement is required before beginning Revision A CAD.
The first PLA fit print must still be checked against the actual devices and
cables before the PETG/ASA functional print.

## Measurements Required After Fabrication

Manufacturer CAD cannot establish the final as-built extrinsic. After the mount
is fabricated, record:

- actual `T_zed_from_array`;
- deviation from the nominal CAD transform;
- support deflection under the installed sensor and cable loads;
- clearance around the ZED field of view and all microphone inlets;
- repeated remove/reinstall pose variation;
- translation and orientation uncertainty;
- audio-visual residuals from the later calibration procedure.

These are properties of the assembled rig, not missing manufacturer
specifications. They are the only stage at which direct measurement of the
finished support becomes mandatory for a calibrated reference-rig claim.

## CAD Entry Condition And Scope

**CAD Revision A may begin.** Its authorized scope is:

1. common rigid sensor carrier;
2. ZED threaded attachment;
3. ReSpeaker three-point cradle and split retaining ring;
4. cable keep-outs and strain-relief features;
5. removable freestanding table base;
6. optional `1/4-20 UNC` interface;
7. common keyed four-M3 platform-adapter face; and
8. nominal frame/datum features needed to export the CAD transform.

The imported ZED and ReSpeaker manufacturer geometry, not manually recreated
bounding boxes, must be used wherever an official model is available. The
public Alex V2 mesh may be imported for an envelope study, but fabrication of
the Alex-specific adapter is outside Revision A until its unit-specific
interface is confirmed. After CAD, the nominal transform must be exported and
the uncertainty plan retained; after fabrication, the as-built measurements in
the previous section remain mandatory.
