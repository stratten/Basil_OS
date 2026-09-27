import AppKit
import Foundation

enum ConversationPastedImageAttachmentWriter {
    enum PasteImageError: LocalizedError {
        case noWritableRepresentation
        case invalidImageData

        var errorDescription: String? {
            switch self {
            case .noWritableRepresentation:
                return "The pasted image could not be converted to PNG data."
            case .invalidImageData:
                return "The pasted image data is invalid."
            }
        }
    }

    static func writePastedImageData(
        _ imageData: [Data],
        fileManager: FileManager = .default,
        date: Date = Date(),
        directory: URL? = nil
    ) throws -> [URL] {
        let images = try imageData.map { data in
            guard let image = NSImage(data: data) else {
                throw PasteImageError.invalidImageData
            }
            return image
        }
        return try writePastedImages(
            images,
            fileManager: fileManager,
            date: date,
            directory: directory
        )
    }

    static func writePastedImages(
        _ images: [NSImage],
        fileManager: FileManager = .default,
        date: Date = Date(),
        directory: URL? = nil
    ) throws -> [URL] {
        guard !images.isEmpty else { return [] }

        let outputDirectory = directory ?? defaultPasteDirectory(fileManager: fileManager)
        try fileManager.createDirectory(
            at: outputDirectory,
            withIntermediateDirectories: true
        )

        let timestamp = filenameTimestamp(for: date)
        return try images.enumerated().map { index, image in
            let data = try pngData(for: image)
            let url = outputDirectory.appendingPathComponent(
                "conversation_paste_\(timestamp)_\(index + 1).png"
            )
            try data.write(to: url, options: .atomic)
            return url
        }
    }

    static func pngData(for image: NSImage) throws -> Data {
        guard let tiffData = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiffData),
              let pngData = bitmap.representation(using: .png, properties: [:]),
              !pngData.isEmpty
        else {
            throw PasteImageError.noWritableRepresentation
        }
        return pngData
    }

    private static func defaultPasteDirectory(fileManager: FileManager) -> URL {
        fileManager.temporaryDirectory
            .appendingPathComponent("Basil", isDirectory: true)
            .appendingPathComponent("conversation-paste", isDirectory: true)
    }

    private static func filenameTimestamp(for date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyyMMdd_HHmmss_SSS"
        return formatter.string(from: date)
    }
}
