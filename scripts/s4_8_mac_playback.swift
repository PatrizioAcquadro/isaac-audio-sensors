#!/usr/bin/swift
import AVFoundation
import CryptoKit
import Foundation

enum PlaybackError: Error, CustomStringConvertible {
    case invalidArgument(String)
    case invalidAsset(String)
    case invalidCommand(String)
    case renderStartTimeout
    case playbackCompletionTimeout

    var description: String {
        switch self {
        case .invalidArgument(let message),
             .invalidAsset(let message),
             .invalidCommand(let message):
            return message
        case .renderStartTimeout:
            return "CoreAudio did not render a nonzero reference frame"
        case .playbackCompletionTimeout:
            return "CoreAudio did not report data-played-back completion"
        }
    }
}

func monotonicNanoseconds() -> UInt64 {
    DispatchTime.now().uptimeNanoseconds
}

func emit(_ event: String, _ values: [String: Any] = [:]) {
    var payload = values
    payload["schema"] = "ias.s4_8.mac_playback_event.v2"
    payload["event"] = event
    let data = try! JSONSerialization.data(
        withJSONObject: payload,
        options: [.sortedKeys]
    )
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0a]))
}

func sha256(_ url: URL) throws -> String {
    let data = try Data(contentsOf: url, options: [.mappedIfSafe])
    return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

func arguments() throws -> (asset: URL, expectedSHA256: String, gain: Float) {
    var values: [String: String] = [:]
    var index = 1
    while index < CommandLine.arguments.count {
        let key = CommandLine.arguments[index]
        guard key.hasPrefix("--"), index + 1 < CommandLine.arguments.count else {
            throw PlaybackError.invalidArgument("playback arguments are invalid")
        }
        values[key] = CommandLine.arguments[index + 1]
        index += 2
    }
    guard
        let assetValue = values["--asset"],
        let expectedSHA256 = values["--expected-sha256"],
        expectedSHA256.count == 64,
        expectedSHA256.allSatisfy({ $0.isHexDigit && !$0.isUppercase }),
        let gainValue = values["--gain"],
        let gain = Float(gainValue),
        gain.isFinite,
        gain > 0.0,
        gain <= 1.0,
        values.count == 3
    else {
        throw PlaybackError.invalidArgument("playback arguments are invalid")
    }
    let asset = URL(
        fileURLWithPath: NSString(string: assetValue).expandingTildeInPath
    ).standardizedFileURL
    return (asset, expectedSHA256, gain)
}

func firstNonzeroFrame(_ buffer: AVAudioPCMBuffer) -> Int? {
    guard
        let channels = buffer.floatChannelData,
        buffer.format.commonFormat == .pcmFormatFloat32
    else {
        return nil
    }
    let frameCount = Int(buffer.frameLength)
    let channelCount = Int(buffer.format.channelCount)
    for frame in 0..<frameCount {
        for channel in 0..<channelCount where channels[channel][frame] != 0.0 {
            return frame
        }
    }
    return nil
}

func renderedFrameNanoseconds(
    when: AVAudioTime,
    frameOffset: Int,
    sampleRate: Double,
    outputPresentationLatencyNanoseconds: UInt64
) -> UInt64 {
    let offsetNanoseconds = UInt64(
        (Double(frameOffset) / sampleRate * 1_000_000_000.0).rounded()
    )
    guard when.isHostTimeValid else {
        return monotonicNanoseconds()
            + offsetNanoseconds
            + outputPresentationLatencyNanoseconds
    }
    let bufferStartNanoseconds = UInt64(
        (AVAudioTime.seconds(forHostTime: when.hostTime) * 1_000_000_000.0)
            .rounded()
    )
    return bufferStartNanoseconds
        + offsetNanoseconds
        + outputPresentationLatencyNanoseconds
}

func run() throws {
    let args = try arguments()
    guard FileManager.default.fileExists(atPath: args.asset.path) else {
        throw PlaybackError.invalidAsset("playback asset is missing")
    }
    guard try sha256(args.asset) == args.expectedSHA256 else {
        throw PlaybackError.invalidAsset("playback asset hash mismatch")
    }

    let file = try AVAudioFile(forReading: args.asset)
    let fileFormat = file.fileFormat
    guard
        fileFormat.sampleRate == 48_000.0,
        fileFormat.channelCount == 1,
        fileFormat.commonFormat == .pcmFormatInt16,
        file.length == 864_000
    else {
        throw PlaybackError.invalidAsset("playback asset format mismatch")
    }
    guard
        let buffer = AVAudioPCMBuffer(
            pcmFormat: file.processingFormat,
            frameCapacity: AVAudioFrameCount(file.length)
        )
    else {
        throw PlaybackError.invalidAsset("playback buffer allocation failed")
    }
    try file.read(into: buffer)
    guard buffer.frameLength == 864_000 else {
        throw PlaybackError.invalidAsset("playback buffer is incomplete")
    }
    guard let sourceFirstNonzeroFrame = firstNonzeroFrame(buffer) else {
        throw PlaybackError.invalidAsset("playback asset has no nonzero frame")
    }
    let sourceFirstNonzeroNanoseconds = UInt64(
        (
            Double(sourceFirstNonzeroFrame)
                / buffer.format.sampleRate * 1_000_000_000.0
        ).rounded()
    )

    let engine = AVAudioEngine()
    let player = AVAudioPlayerNode()
    let startSemaphore = DispatchSemaphore(value: 0)
    let completionSemaphore = DispatchSemaphore(value: 0)
    let observationLock = NSLock()
    var playbackRequested = false
    var renderObservation: [String: Any]?
    var outputPresentationLatencyNanoseconds: UInt64 = 0

    engine.attach(player)
    engine.connect(player, to: engine.mainMixerNode, format: buffer.format)
    player.volume = args.gain
    let outputFormat = engine.mainMixerNode.outputFormat(forBus: 0)
    engine.mainMixerNode.installTap(
        onBus: 0,
        bufferSize: 256,
        format: outputFormat
    ) { renderedBuffer, when in
        observationLock.lock()
        let shouldInspect = playbackRequested && renderObservation == nil
        let presentationLatencyNanoseconds =
            outputPresentationLatencyNanoseconds
        observationLock.unlock()
        guard
            shouldInspect,
            let offset = firstNonzeroFrame(renderedBuffer)
        else {
            return
        }
        let observedNanoseconds = renderedFrameNanoseconds(
            when: when,
            frameOffset: offset,
            sampleRate: renderedBuffer.format.sampleRate,
            outputPresentationLatencyNanoseconds:
                presentationLatencyNanoseconds
        )
        observationLock.lock()
        if renderObservation == nil {
            renderObservation = [
                "presentation_start_monotonic_ns": NSNumber(
                    value: observedNanoseconds
                ),
                "first_nonzero_frame_offset": offset,
                "render_buffer_frame_count": Int(renderedBuffer.frameLength),
                "render_sample_rate_hz": renderedBuffer.format.sampleRate,
                "render_host_time_valid": when.isHostTimeValid,
                "output_presentation_latency_ns": NSNumber(
                    value: outputPresentationLatencyNanoseconds
                ),
                "start_observation":
                    "coreaudio_first_nonzero_presented_frame",
            ]
            observationLock.unlock()
            startSemaphore.signal()
        } else {
            observationLock.unlock()
        }
    }
    engine.prepare()
    try engine.start()
    observationLock.lock()
    outputPresentationLatencyNanoseconds = UInt64(
        (engine.outputNode.presentationLatency * 1_000_000_000.0).rounded()
    )
    observationLock.unlock()
    defer {
        player.stop()
        engine.mainMixerNode.removeTap(onBus: 0)
        engine.stop()
    }

    emit(
        "armed",
        [
            "asset_sha256": args.expectedSHA256,
            "asset_format": [
                "sample_rate_hz": fileFormat.sampleRate,
                "channel_count": fileFormat.channelCount,
                "sample_width_bytes": 2,
                "frame_count": file.length,
                "compression": "NONE",
            ],
            "gain": args.gain,
            "helper_monotonic_ns": NSNumber(value: monotonicNanoseconds()),
            "start_observation": "coreaudio_first_nonzero_presented_frame",
            "completion_observation": "coreaudio_data_played_back",
            "output_presentation_latency_ns": NSNumber(
                value: outputPresentationLatencyNanoseconds
            ),
        ]
    )

    guard readLine() == "SYNC" else {
        throw PlaybackError.invalidCommand(
            "authenticated SYNC command was not received"
        )
    }
    emit(
        "clock_sync",
        ["helper_monotonic_ns": NSNumber(value: monotonicNanoseconds())]
    )
    guard
        let startCommand = readLine(),
        startCommand.hasPrefix("START_AT "),
        let targetPresentationNanoseconds = UInt64(
            startCommand.dropFirst("START_AT ".count)
        ),
        targetPresentationNanoseconds
            > outputPresentationLatencyNanoseconds
                + sourceFirstNonzeroNanoseconds
    else {
        throw PlaybackError.invalidCommand(
            "authenticated START_AT command was not received"
        )
    }
    let renderStartNanoseconds =
        targetPresentationNanoseconds
            - outputPresentationLatencyNanoseconds
            - sourceFirstNonzeroNanoseconds
    guard renderStartNanoseconds > monotonicNanoseconds() else {
        throw PlaybackError.invalidCommand(
            "authenticated START_AT target is not in the future"
        )
    }

    player.scheduleBuffer(
        buffer,
        at: nil,
        options: [],
        completionCallbackType: .dataPlayedBack
    ) { _ in
        completionSemaphore.signal()
    }
    observationLock.lock()
    playbackRequested = true
    observationLock.unlock()
    player.play(
        at: AVAudioTime(
            hostTime: AVAudioTime.hostTime(
                forSeconds: Double(renderStartNanoseconds) / 1_000_000_000.0
            )
        )
    )

    guard startSemaphore.wait(timeout: .now() + 5.0) == .success else {
        throw PlaybackError.renderStartTimeout
    }
    observationLock.lock()
    let startValues = renderObservation
    observationLock.unlock()
    guard let startValues else {
        throw PlaybackError.renderStartTimeout
    }
    emit("playback_started", startValues)

    guard completionSemaphore.wait(timeout: .now() + 25.0) == .success else {
        throw PlaybackError.playbackCompletionTimeout
    }
    emit(
        "playback_completed",
        [
            "playback_exit_status": 0,
            "helper_monotonic_ns": NSNumber(value: monotonicNanoseconds()),
            "completion_observation": "coreaudio_data_played_back",
            "stderr": "",
        ]
    )
}

do {
    try run()
    exit(0)
} catch {
    emit(
        "failed",
        [
            "error_type": String(describing: type(of: error)),
            "error": String(describing: error),
            "helper_monotonic_ns": NSNumber(value: monotonicNanoseconds()),
        ]
    )
    exit(1)
}
