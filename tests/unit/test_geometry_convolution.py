"""Native-response convolution retains the sample clock across reads and tails."""

import numpy as np
import pytest

from isaac_audio_sensors.isaac.acoustic_scene._convolution import ConvolutionStream

pytest.importorskip("scipy")


def test_partition_independent_response_transition_and_tail():
    rng = np.random.default_rng(12)
    signal = rng.normal(size=321).astype(np.float32)
    signal[170:] = 0
    first = [np.r_[np.zeros(17), 0.3, 0.2], np.r_[np.zeros(22), 0.4]]
    second = [np.r_[np.zeros(20), 0.3, 0.2], np.r_[np.zeros(27), 0.4]]

    def run(sizes):
        stream = ConvolutionStream(2, 100, 40)
        stream.update(first)
        rows, cursor = [], 0
        for size in sizes:
            if cursor == 100:
                stream.update(second)
            rows.append(stream.process(signal[cursor : cursor + size]))
            cursor += size
        return np.concatenate(rows, axis=1)

    continuous = run([100, 221])
    fragmented = run([13, 87, 9, 17, 31, 164])
    np.testing.assert_allclose(fragmented, continuous, atol=2e-7, rtol=2e-6)
    assert np.max(abs(fragmented[:, 170:195])) > 0.1
    np.testing.assert_allclose(fragmented[:, 198:], 0, atol=2e-7)
    np.testing.assert_allclose(fragmented[:, :17], 0, atol=2e-7)


def test_capacity_failure_preserves_previous_response():
    stream = ConvolutionStream(1, 8, 4)
    stream.update([np.array([1.0])])
    with pytest.raises(ValueError, match="history"):
        stream.update([np.ones(10)])
    np.testing.assert_allclose(stream.process([1.0, 2.0]), [[1.0, 2.0]], atol=1e-7)
