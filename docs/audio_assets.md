# Audio Assets

How `audio_asset_path` values resolve for the `room_acoustics` backend, and
how to use external audio corpora.

## Generated assets

`generated://impulse`, `generated://pulse`, and the default
`generated://deterministic_pulse` synthesize deterministic waveforms seeded by
`source_id`; they need no files and no optional dependencies. Each source
emits a phase-continuous two-tone signal over its whole scheduled interval
(impulse/pulse modes add transient spikes at fixed source-relative offsets),
so consecutive frame windows concatenate without discontinuities.

## File-backed assets

Any other `audio_asset_path` is loaded with `soundfile` from the `room`
extra. The rules are intentionally narrow:

- the path must be **relative** and resolve **inside the current checkout**
  (no absolute paths, no `..` components);
- the file must exist; multichannel files are downmixed to mono by averaging;
- a sample-rate mismatch with the frame sample rate is resolved automatically
  with `scipy.signal.resample_poly` (polyphase resampling on the
  integer-ratio reduction of the two rates).

A source that started before the current window resumes from its elapsed
offset into the file, so a long recording plays through continuously across
frames instead of restarting every window.

## External corpora (ESC-50 / FSD50K style)

Keep downloaded datasets out of git: the repository ignores `data/`,
`outputs/`, `generated/`, and all `*.wav` files. The convention is to place
corpora under `data/` in the checkout and reference clips with relative
paths:

```bash
# example layout
data/esc50/audio/1-100032-A-0.wav
data/fsd50k/dev_audio/64760.wav
```

```toml
[[sources]]
source_id = "dog_bark"
prim_path = "/World/Sources/DogBark"
class_label = "Dog"
audio_asset_path = "data/esc50/audio/1-100032-A-0.wav"
start_time_s = 0.5
duration_s = 5.0
gain_db = -3.0
```

ESC-50 ships 44.1 kHz clips and FSD50K mixed rates; both resample
automatically to the configured sensor rate (48 kHz by default). Respect each
dataset's license when redistributing traces or exported waveforms derived
from it.

## Test fixtures

Tests generate WAV fixtures at run time instead of committing binaries,
writing them with `soundfile` into pytest's `tmp_path` and pointing the
working directory there so relative-path validation passes:

```python
def test_with_file_asset(monkeypatch, tmp_path):
    soundfile = pytest.importorskip("soundfile")
    monkeypatch.chdir(tmp_path)
    soundfile.write("fixture_tone.wav", tone, 8_000)
    source = AudioSourceSpec(..., audio_asset_path="fixture_tone.wav")
```

## Exported waveforms

Waveform export (the other direction: simulation to WAV) is documented in
[Room Acoustics](room_acoustics.md#waveform-export). Exported files land in
the configured `waveform_dir` — keep it under an ignored directory such as
`outputs/` so artifacts stay out of git.
