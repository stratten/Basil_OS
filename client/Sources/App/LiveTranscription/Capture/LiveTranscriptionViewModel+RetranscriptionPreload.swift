import Foundation

/// Decision and request-building logic for loading the mid-recording retranscription model at Start.
///
/// Loading a local Parakeet model holds the backend's Python GIL for a few seconds, which freezes every live WebSocket on the backend. Doing it once, before the capture sockets open, keeps that pause out of the middle of a recording.
enum RetranscriptionModelPreload {
    /// Upper bound on how long Start waits for the model load before continuing without it.
    static let requestTimeoutSeconds: TimeInterval = 30

    /// A preload only helps when the mid-recording cadence will actually run and live transcription is on, because the cadence loop skips ticks when live transcription is off.
    static func shouldPreload(cadenceEnabled: Bool, liveTranscriptionEnabled: Bool, model: String) -> Bool {
        guard PostProcessingAutomation.shouldArmMidRecordingCadence(enabled: cadenceEnabled) else { return false }
        guard liveTranscriptionEnabled else { return false }
        return !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// Builds the POST request for the backend preload endpoint.
    static func makeRequest(port: Int, model: String) -> URLRequest? {
        guard let url = URL(string: "http://localhost:\(port)/meetings/prepare-retranscription-model") else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = requestTimeoutSeconds
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["model": model])
        return request
    }
}

extension LiveTranscriptionViewModel {
    /// Best-effort: asks the backend to load the retranscription model before recording begins. Any failure is logged and ignored, because the first cadence tick still loads the model on demand.
    func preloadRetranscriptionModelIfNeeded() async {
        guard RetranscriptionModelPreload.shouldPreload(
            cadenceEnabled: sessionAutoRetranscribeDuringRecording,
            liveTranscriptionEnabled: sessionLiveTranscriptionEnabled,
            model: postProcessingModel
        ) else { return }

        guard let request = RetranscriptionModelPreload.makeRequest(
            port: APIClient.shared.currentPort,
            model: postProcessingModel
        ) else { return }

        statusMessage = "Preparing transcription model..."
        let startedAt = Date()
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            let elapsed = String(format: "%.1f", Date().timeIntervalSince(startedAt))
            DevLogger.shared.info("Retranscription model preload finished: status=\(statusCode) elapsed=\(elapsed)s", context: "LiveTranscriptionViewModel")
        } catch {
            DevLogger.shared.warning("Retranscription model preload failed; the first cadence tick will load it: \(error.localizedDescription)", context: "LiveTranscriptionViewModel")
        }
        statusMessage = "Connecting to server..."
    }
}
