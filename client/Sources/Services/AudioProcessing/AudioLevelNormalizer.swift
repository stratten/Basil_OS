import Foundation

enum AudioLevelNormalizer {
    static let silenceFloorDecibels: Float = -50

    static func normalizedLevel(
        sumOfSquares: Float,
        sampleCount: Int
    ) -> Float {
        guard sampleCount > 0, sumOfSquares.isFinite, sumOfSquares > 0 else {
            return 0
        }

        let rms = sqrt(sumOfSquares / Float(sampleCount))
        let decibels = 20 * log10(max(rms, Float.leastNonzeroMagnitude))
        return max(
            0,
            min(1, (decibels - silenceFloorDecibels) / -silenceFloorDecibels)
        )
    }

    static func normalizedLevel(from samples: UnsafeBufferPointer<Int16>) -> Float {
        guard !samples.isEmpty else {
            return 0
        }

        let fullScale = Float(Int16.max)
        let sumOfSquares = samples.reduce(Float.zero) { partialResult, sample in
            let normalizedSample = Float(sample) / fullScale
            return partialResult + (normalizedSample * normalizedSample)
        }
        return normalizedLevel(
            sumOfSquares: sumOfSquares,
            sampleCount: samples.count
        )
    }
}
