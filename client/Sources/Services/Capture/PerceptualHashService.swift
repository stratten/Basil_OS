import AppKit
import Foundation

enum PerceptualHashService {
    static func differenceHash(imagePath: String) -> String? {
        guard let imageData = FileManager.default.contents(atPath: imagePath),
              let source = NSBitmapImageRep(data: imageData),
              source.pixelsWide > 0,
              source.pixelsHigh > 0
        else {
            return nil
        }

        var luminancePixels = [UInt8](repeating: 0, count: 9 * 8)
        for row in 0..<8 {
            for column in 0..<9 {
                let x = sampleCoordinate(
                    sample: column,
                    samples: 9,
                    sourceLength: source.pixelsWide
                )
                let y = sampleCoordinate(
                    sample: row,
                    samples: 8,
                    sourceLength: source.pixelsHigh
                )
                guard let color = source.colorAt(x: x, y: y)?
                    .usingColorSpace(NSColorSpace.deviceRGB) else {
                    return nil
                }
                luminancePixels[row * 9 + column] = luminance(
                    red: color.redComponent,
                    green: color.greenComponent,
                    blue: color.blueComponent
                )
            }
        }

        return differenceHash(luminance: luminancePixels)
    }

    static func differenceHash(luminance: [UInt8]) -> String? {
        guard luminance.count == 9 * 8 else { return nil }

        var value: UInt64 = 0
        for row in 0..<8 {
            let rowOffset = row * 9
            for column in 0..<8 {
                value <<= 1
                if luminance[rowOffset + column] > luminance[rowOffset + column + 1] {
                    value |= 1
                }
            }
        }

        return String(format: "%016llx", value)
    }

    private static func sampleCoordinate(sample: Int, samples: Int, sourceLength: Int) -> Int {
        guard sourceLength > 1 else { return 0 }
        return Int(
            (Double(sample) * Double(sourceLength - 1) / Double(samples - 1)).rounded()
        )
    }

    private static func luminance(red: CGFloat, green: CGFloat, blue: CGFloat) -> UInt8 {
        UInt8((0.299 * red + 0.587 * green + 0.114 * blue) * 255)
    }
}
