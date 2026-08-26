from __future__ import annotations

import numpy as np

from isaac_audio_sensors.core.backends.room_acoustics.signals import (
    _file_source_content,
)


def test_file_source_content_plays_once_by_default() -> None:
    content = _file_source_content(
        np.array([1.0, 2.0, 3.0]),
        elapsed_samples=0,
        content_samples=8,
        loop_count=0,
    )

    assert content.tolist() == [1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_file_source_content_honors_finite_additional_loops() -> None:
    content = _file_source_content(
        np.array([1.0, 2.0, 3.0]),
        elapsed_samples=2,
        content_samples=8,
        loop_count=1,
    )

    assert content.tolist() == [3.0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 0.0]


def test_file_source_content_honors_infinite_loop_at_elapsed_offset() -> None:
    content = _file_source_content(
        np.array([1.0, 2.0, 3.0]),
        elapsed_samples=4,
        content_samples=7,
        loop_count=-1,
    )

    assert content.tolist() == [2.0, 3.0, 1.0, 2.0, 3.0, 1.0, 2.0]
