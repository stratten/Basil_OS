import XCTest
@testable import BasilClient

final class PerceptualHashServiceTests: XCTestCase {
    func testIdenticalLuminanceRastersProduceIdenticalHashes() {
        let raster = luminanceRaster(descending: true)
        XCTAssertEqual(
            PerceptualHashService.differenceHash(luminance: raster),
            PerceptualHashService.differenceHash(luminance: raster)
        )
    }

    func testContrastingLuminanceRastersProduceDifferentHashes() {
        XCTAssertNotEqual(
            PerceptualHashService.differenceHash(luminance: luminanceRaster(descending: true)),
            PerceptualHashService.differenceHash(luminance: luminanceRaster(descending: false))
        )
    }

    func testMalformedLuminanceRasterHasNoHash() {
        XCTAssertNil(PerceptualHashService.differenceHash(luminance: [0, 1]))
    }

    private func luminanceRaster(descending: Bool) -> [UInt8] {
        (0..<8).flatMap { _ in
            (0..<9).map { column in
                descending ? UInt8(255 - column * 28) : UInt8(column * 28)
            }
        }
    }
}
