"""Receiver-clock convolution with bounded source history and causal IR updates."""

import numpy as np


class ConvolutionStream:
    """Apply native impulse responses without pre-rendering future PCM."""

    def __init__(self, microphones, history_samples, transition_samples):
        self.microphones = microphones
        self.history = np.zeros(history_samples, np.float32)
        self.transition_samples = transition_samples
        self.current = None
        self.previous = None
        self.transition = transition_samples

    def update(self, responses):
        length = max(map(len, responses))
        if length > len(self.history) + 1:
            raise ValueError("Native impulse response exceeds the configured history.")
        impulse = np.array(
            [np.pad(row, (0, length - len(row))) for row in responses], dtype=np.float32
        )
        if impulse.shape[0] != self.microphones:
            raise ValueError("Native response microphone count changed.")
        if self.current is not None and np.array_equal(self.current, impulse):
            return
        if self.previous is not None and self.transition < self.transition_samples:
            weight = self.transition / self.transition_samples
            size = max(self.previous.shape[1], self.current.shape[1])
            self.current = (1 - weight) * np.pad(
                self.previous, ((0, 0), (0, size - self.previous.shape[1]))
            ) + weight * np.pad(
                self.current, ((0, 0), (0, size - self.current.shape[1]))
            )
        self.previous = self.current
        self.current = impulse
        self.transition = 0 if self.previous is not None else self.transition_samples

    def process(self, samples):
        from scipy.signal import fftconvolve

        values = np.asarray(samples, dtype=np.float32)
        if self.current is None:
            raise RuntimeError("Native impulse responses are not initialized.")
        count = len(values)
        if count == 0:
            return np.zeros((self.microphones, 0), np.float32)
        extended = np.concatenate((self.history, values))

        def render(impulse):
            length = impulse.shape[1]
            input_values = extended[len(self.history) - length + 1 :]
            return fftconvolve(input_values[None], impulse, mode="full", axes=-1)[
                :, length - 1 : length - 1 + count
            ]

        output = render(self.current)
        if self.previous is not None and self.transition < self.transition_samples:
            weight = np.minimum(
                1.0,
                (self.transition + np.arange(1, count + 1)) / self.transition_samples,
            )
            output = (1 - weight)[None] * render(self.previous) + weight[None] * output
            self.transition += count
            if self.transition >= self.transition_samples:
                self.previous = None
        self.history[:] = extended[-len(self.history) :]
        return output.astype(np.float32)
