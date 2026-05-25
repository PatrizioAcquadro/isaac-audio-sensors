# Showcase

Standalone showcase website:

<https://isaac-audio-showcase-site.vercel.app>

The showcase is a separate web repository and is linked here rather than copied
into this package. It presents visual/audio evidence, synchronized media,
generated reports, and validation artifacts for example scenes.

This package repository tracks source code, docs, configs, examples, tests, and
small scripts. It does not track generated MP4, WAV, PDF, PNG, SVG, USD output
dumps, or downloaded third-party scene assets.

For this repository's local live validation record, run:

```bash
make live-evidence-report
```

The report generator `scripts/generate_live_evidence_report.py` reads the
canonical artifacts under `outputs/isaac_audio_sensors/`, including
`outputs/isaac_audio_sensors/isaac_sim_live_smoke.json`,
`outputs/isaac_audio_sensors/isaac_lab_live_smoke_gpu.json`, and
`outputs/isaac_audio_sensors/omniverse_extension_live_ux.json`. It writes the
ignored source/PDF pair:

- `outputs/isaac_audio_sensors/live_validation_evidence.md`
- `outputs/isaac_audio_sensors/live_validation_evidence.pdf`
