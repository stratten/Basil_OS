import Foundation

@MainActor
final class SystemAudioMeterState {
    private var noiseGate = SystemAudioNoiseGate()

    func reset() {
        noiseGate.reset()
    }

    func filteredLevel(for rawLevel: Float) -> Float {
        noiseGate.filteredLevel(for: rawLevel)
    }
}
