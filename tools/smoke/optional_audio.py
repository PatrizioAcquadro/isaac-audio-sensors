from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pyroomacoustics as pra
import scipy
import soundfile


def main() -> int:
    samples = np.linspace(-0.5, 0.5, 256, dtype=np.float32)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "codec.flac"
        soundfile.write(path, samples, 16_000, format="FLAC")
        restored, sample_rate_hz = soundfile.read(path, dtype="float32")
    room = pra.ShoeBox((3.0, 3.0, 2.5), fs=16_000, max_order=0)
    room.add_source((1.0, 1.0, 1.0), signal=samples)
    room.add_microphone((2.0, 1.0, 1.0))
    room.simulate()
    assert sample_rate_hz == 16_000
    assert restored.shape == samples.shape
    assert np.asarray(room.mic_array.signals).size > 0
    print(
        json.dumps(
            {
                "pyroomacoustics": pra.__version__,
                "scipy": scipy.__version__,
                "soundfile": soundfile.__version__,
                "status": "passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
