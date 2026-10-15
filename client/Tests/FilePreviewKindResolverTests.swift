import AppKit
import XCTest
@testable import BasilClient

final class FilePreviewKindResolverTests: XCTestCase {
    private var temporaryDirectory: URL!

    override func setUpWithError() throws {
        temporaryDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("FilePreviewKindResolverTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: temporaryDirectory)
    }

    private func onePixelPNGData() throws -> Data {
        let bitmap = try XCTUnwrap(NSBitmapImageRep(
            bitmapDataPlanes: nil,
            pixelsWide: 1,
            pixelsHigh: 1,
            bitsPerSample: 8,
            samplesPerPixel: 4,
            hasAlpha: true,
            isPlanar: false,
            colorSpaceName: .deviceRGB,
            bytesPerRow: 0,
            bitsPerPixel: 0
        ))
        return try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
    }

    func testSupportedImageExtensionsMapToImageCaseInsensitively() {
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "png"), "image")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "JPG"), "image")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "jpeg"), "image")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "gif"), "image")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "webp"), "image")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "bmp"), "image")
    }

    func testExcludedAndUnknownExtensionsStayUnsupported() {
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "svg"), "unsupported")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "heic"), "unsupported")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "tiff"), "unsupported")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "xyz"), "unsupported")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: ""), "unsupported")
    }

    func testExistingTextAndPDFKindsAreUnchanged() {
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "md"), "markdown")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "html"), "htmlSource")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "py"), "code")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "csv"), "text")
        XCTAssertEqual(FilePreviewKindResolver.kind(forExtension: "pdf"), "pdf")
    }

    func testMimeTypesCoverEverySupportedImageExtension() {
        XCTAssertEqual(FilePreviewKindResolver.mimeType(forImageExtension: "PNG"), "image/png")
        XCTAssertEqual(FilePreviewKindResolver.mimeType(forImageExtension: "jpg"), "image/jpeg")
        XCTAssertEqual(FilePreviewKindResolver.mimeType(forImageExtension: "jpeg"), "image/jpeg")
        XCTAssertEqual(FilePreviewKindResolver.mimeType(forImageExtension: "gif"), "image/gif")
        XCTAssertEqual(FilePreviewKindResolver.mimeType(forImageExtension: "webp"), "image/webp")
        XCTAssertEqual(FilePreviewKindResolver.mimeType(forImageExtension: "bmp"), "image/bmp")
        XCTAssertNil(FilePreviewKindResolver.mimeType(forImageExtension: "svg"))
    }

    func testGeneratedPNGProducesDataURLThatRoundTripsToSameBytes() throws {
        let data = try onePixelPNGData()
        let url = temporaryDirectory.appendingPathComponent("pixel.png")
        try data.write(to: url)

        let result = FilePreviewKindResolver.imageDataURL(at: url)

        guard case .success(let dataURL) = result else {
            return XCTFail("Expected a data URL, got \(result)")
        }
        let prefix = "data:image/png;base64,"
        XCTAssertTrue(dataURL.hasPrefix(prefix))
        XCTAssertEqual(Data(base64Encoded: String(dataURL.dropFirst(prefix.count))), data)
    }

    func testTextBytesAtImagePathAreUndecodable() throws {
        let url = temporaryDirectory.appendingPathComponent("not-an-image.png")
        try Data("this is plain text".utf8).write(to: url)

        XCTAssertEqual(FilePreviewKindResolver.imageDataURL(at: url), .failure(.undecodable))
    }

    func testMissingFileIsUndecodable() {
        let url = temporaryDirectory.appendingPathComponent("missing.png")

        XCTAssertEqual(FilePreviewKindResolver.imageDataURL(at: url), .failure(.undecodable))
    }

    func testFileOneByteOverTheCapIsTooLargeBeforeDecoding() throws {
        let url = temporaryDirectory.appendingPathComponent("huge.png")
        let overCap = Int(FilePreviewKindResolver.maximumImageBytes) + 1
        try Data(count: overCap).write(to: url)

        XCTAssertEqual(FilePreviewKindResolver.imageDataURL(at: url), .failure(.tooLarge))
    }

    func testFailureMessagesMatchTheUserFacingCopy() {
        XCTAssertEqual(FilePreviewImageError.tooLarge.userMessage, "This image is too large to preview here. Use Open File.")
        XCTAssertEqual(FilePreviewImageError.undecodable.userMessage, "This image could not be opened for preview.")
    }
}
