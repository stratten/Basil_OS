import AppKit
import XCTest
@testable import BasilClient

final class ConversationPastedImageAttachmentWriterTests: XCTestCase {
    private var tempDirectory: URL!

    override func setUpWithError() throws {
        try super.setUpWithError()
        tempDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ConversationPastedImageAttachmentWriterTests", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: tempDirectory,
            withIntermediateDirectories: true
        )
    }

    override func tearDownWithError() throws {
        if let tempDirectory {
            try? FileManager.default.removeItem(at: tempDirectory)
        }
        tempDirectory = nil
        try super.tearDownWithError()
    }

    func testWritePastedImagesCreatesNonEmptyPngFiles() throws {
        let images = [
            makeImage(color: .systemBlue),
            makeImage(color: .systemGreen),
        ]
        let date = Date(timeIntervalSince1970: 1_781_624_580.123)

        let urls = try ConversationPastedImageAttachmentWriter.writePastedImages(
            images,
            date: date,
            directory: tempDirectory
        )

        XCTAssertEqual(urls.count, 2)
        XCTAssertEqual(Set(urls.map(\.lastPathComponent)).count, 2)
        for url in urls {
            XCTAssertEqual(url.pathExtension, "png")
            XCTAssertTrue(FileManager.default.fileExists(atPath: url.path))
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            let fileSize = try XCTUnwrap(attributes[.size] as? NSNumber)
            XCTAssertGreaterThan(fileSize.intValue, 0)
        }
    }

    func testWritePastedImagesReturnsEmptyListForNoImages() throws {
        let urls = try ConversationPastedImageAttachmentWriter.writePastedImages(
            [],
            directory: tempDirectory
        )

        XCTAssertTrue(urls.isEmpty)
    }

    func testWritePastedImageDataCreatesPngFile() throws {
        let sourceImage = makeImage(color: .systemPurple)
        let sourceData = try ConversationPastedImageAttachmentWriter.pngData(for: sourceImage)

        let urls = try ConversationPastedImageAttachmentWriter.writePastedImageData(
            [sourceData],
            directory: tempDirectory
        )

        XCTAssertEqual(urls.count, 1)
        XCTAssertEqual(urls[0].pathExtension, "png")
        XCTAssertTrue(FileManager.default.fileExists(atPath: urls[0].path))
    }

    func testWritePastedImageDataRejectsMalformedBytes() {
        XCTAssertThrowsError(
            try ConversationPastedImageAttachmentWriter.writePastedImageData(
                [Data("not-an-image".utf8)],
                directory: tempDirectory
            )
        ) { error in
            XCTAssertEqual(
                error.localizedDescription,
                "The pasted image data is invalid."
            )
        }
    }

    private func makeImage(color: NSColor) -> NSImage {
        let size = NSSize(width: 12, height: 12)
        let image = NSImage(size: size)
        image.lockFocus()
        color.setFill()
        NSBezierPath(rect: NSRect(origin: .zero, size: size)).fill()
        image.unlockFocus()
        return image
    }
}
