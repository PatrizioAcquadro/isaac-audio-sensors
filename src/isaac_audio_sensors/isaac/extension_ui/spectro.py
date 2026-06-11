"""Waveform-envelope and spectrogram rasters for the Audio Output panel.

numpy-only (``np.fft.rfft`` STFT, no scipy) so previews work in any Isaac
python environment; rendering reuses the dark-panel style of the instrument
rasters and the same ``ByteImageProvider`` display path.
"""

from __future__ import annotations

import numpy as np

from .instruments import COLOR_CLEAR

WAVEFORM_IMAGE_WIDTH = 420
WAVEFORM_IMAGE_HEIGHT = 96
SPECTROGRAM_IMAGE_WIDTH = 420
SPECTROGRAM_IMAGE_HEIGHT = 128
SPECTROGRAM_FLOOR_DB = -80.0


def mixdown(samples: np.ndarray) -> np.ndarray:
    """Average ``[channel, frame]`` samples into one mono float64 track."""

    data = np.asarray(samples, dtype=np.float64)
    if data.ndim == 1:
        return data
    if data.size == 0:
        return np.zeros(0, dtype=np.float64)
    return data.mean(axis=0)


def waveform_envelope(samples: np.ndarray, *, bins: int) -> np.ndarray:
    """Per-bin (min, max) envelope of the mono mixdown, shape ``(bins, 2)``."""

    mono = mixdown(samples)
    bins = max(1, int(bins))
    envelope = np.zeros((bins, 2), dtype=np.float64)
    if mono.size == 0:
        return envelope
    edges = np.linspace(0, mono.size, bins + 1, dtype=np.int64)
    for index in range(bins):
        chunk = mono[edges[index] : max(edges[index + 1], edges[index] + 1)]
        if chunk.size:
            envelope[index, 0] = float(chunk.min())
            envelope[index, 1] = float(chunk.max())
    return envelope


def stft_db(
    samples: np.ndarray,
    *,
    n_fft: int = 512,
    hop: int = 256,
    floor_db: float = SPECTROGRAM_FLOOR_DB,
) -> np.ndarray:
    """Hann-windowed STFT magnitude in dB, shape ``(freq_bins, frames)``."""

    mono = mixdown(samples)
    n_fft = max(16, int(n_fft))
    hop = max(1, int(hop))
    if mono.size < n_fft:
        mono = np.pad(mono, (0, n_fft - mono.size))
    window = np.hanning(n_fft)
    frame_count = 1 + (mono.size - n_fft) // hop
    spectra = np.empty((n_fft // 2 + 1, frame_count), dtype=np.float64)
    for frame in range(frame_count):
        start = frame * hop
        segment = mono[start : start + n_fft] * window
        spectra[:, frame] = np.abs(np.fft.rfft(segment))
    reference = spectra.max()
    if reference <= 0.0:
        return np.full_like(spectra, float(floor_db))
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(spectra / reference)
    return np.clip(db, float(floor_db), 0.0)


def render_waveform_rgba(
    samples: np.ndarray,
    *,
    width: int = WAVEFORM_IMAGE_WIDTH,
    height: int = WAVEFORM_IMAGE_HEIGHT,
) -> np.ndarray:
    """Rasterize the min/max envelope as a green-on-dark waveform strip."""

    width = int(width)
    height = int(height)
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., :3] = 30
    rgba[..., 3] = 255
    rgba[height // 2, :, :3] = 55
    envelope = waveform_envelope(samples, bins=width)
    peak = float(np.abs(envelope).max())
    scale = (height / 2 - 2) / peak if peak > 0 else 0.0
    center = height / 2.0
    color = np.array(
        [int(channel * 255) for channel in COLOR_CLEAR[:3]],
        dtype=np.uint8,
    )
    for column in range(width):
        low, high = envelope[column]
        top = int(round(center - high * scale))
        bottom = int(round(center - low * scale))
        top = max(0, min(height - 1, top))
        bottom = max(0, min(height - 1, bottom))
        rgba[top : bottom + 1, column, :3] = color
    return rgba


def render_spectrogram_rgba(
    samples: np.ndarray,
    *,
    width: int = SPECTROGRAM_IMAGE_WIDTH,
    height: int = SPECTROGRAM_IMAGE_HEIGHT,
    floor_db: float = SPECTROGRAM_FLOOR_DB,
) -> np.ndarray:
    """Rasterize the STFT (low frequencies at the bottom, dark-to-bright)."""

    width = int(width)
    height = int(height)
    db = stft_db(samples, floor_db=floor_db)
    normalized = (db - float(floor_db)) / max(1e-9, -float(floor_db))
    freq_index = np.linspace(0, db.shape[0] - 1, height).astype(np.int64)
    time_index = np.linspace(0, db.shape[1] - 1, width).astype(np.int64)
    grid = normalized[np.ix_(freq_index, time_index)][::-1, :]
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = np.clip(np.rint(255 * np.clip(grid * 2.0 - 1.0, 0.0, 1.0)), 0, 255)
    rgba[..., 1] = np.clip(np.rint(255 * grid), 0, 255)
    rgba[..., 2] = np.clip(np.rint(80 * (1.0 - grid) + 30), 0, 255)
    rgba[..., 3] = 255
    return rgba
