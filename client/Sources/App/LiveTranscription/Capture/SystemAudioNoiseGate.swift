import Foundation

struct SystemAudioNoiseGate {
    static let calibrationObservationCount = 30
    static let baselineAllowance: Float = 0.03

    private var calibrationLevels: [Float] = []
    private(set) var baseline: Float?

    var isCalibrated: Bool {
        baseline != nil
    }

    mutating func reset() {
        calibrationLevels = []
        baseline = nil
    }

    mutating func filteredLevel(for rawLevel: Float) -> Float {
        let level = min(1, max(0, rawLevel))

        guard let baseline else {
            calibrationLevels.append(level)
            if calibrationLevels.count == Self.calibrationObservationCount {
                baseline = median(of: calibrationLevels)
                calibrationLevels = []
            }
            return 0
        }

        let threshold = min(1, baseline + Self.baselineAllowance)
        guard level > threshold, threshold < 1 else {
            return 0
        }
        return (level - threshold) / (1 - threshold)
    }

    private func median(of values: [Float]) -> Float {
        let sortedValues = values.sorted()
        let middleIndex = sortedValues.count / 2
        if sortedValues.count.isMultiple(of: 2) {
            return (sortedValues[middleIndex - 1] + sortedValues[middleIndex]) / 2
        }
        return sortedValues[middleIndex]
    }
}
