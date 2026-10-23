import AppKit
import Foundation

enum FilePreviewImageError: Error, Equatable {
    case tooLarge
    case undecodable

    var userMessage: String {
        switch self {
        case .tooLarge:
            return "This image is too large to preview here. Use Open File."
        case .undecodable:
            return "This image could not be opened for preview."
        }
    }
}

/// Single source of truth for which file extensions the in-app preview supports and how images are delivered to the web layer. Both the inline preview coordinator (Agent Task result widget and Basil Board) and the pop-out preview window delegate here so the two extension tables cannot drift apart.
enum FilePreviewKindResolver {
    /// Images are sent as a base64 data URL inside a JSON payload, so the cap is deliberately well below the size at which `evaluateJavaScript` payloads become a concern. Do not raise it without measuring.
    static let maximumImageBytes: UInt64 = 8_000_000

    static func kind(forExtension fileExtension: String) -> String {
        switch fileExtension.lowercased() {
        case "md", "markdown":
            return "markdown"
        case "html", "htm":
            return "htmlSource"
        // Keep this a superset of the extensions the backend snapshots for task review (`_EXTENSION_KIND` in `artifact_revision_capture.py`). A file the side panel can review must never be "unsupported" here; `filePreviewKindParity.contract.test.ts` (web-components/AgentTaskResult) fails when the two drift.
        case "js", "jsx", "ts", "tsx", "py", "swift", "sh", "sql", "css", "json", "yaml", "yml", "xml",
             "go", "rs", "java", "c", "cpp", "h", "rb", "toml", "ini":
            return "code"
        case "txt", "log", "csv":
            return "text"
        case "pdf":
            return "pdf"
        case "png", "jpg", "jpeg", "gif", "webp", "bmp":
            return "image"
        default:
            return "unsupported"
        }
    }

    static func mimeType(forImageExtension fileExtension: String) -> String? {
        switch fileExtension.lowercased() {
        case "png":
            return "image/png"
        case "jpg", "jpeg":
            return "image/jpeg"
        case "gif":
            return "image/gif"
        case "webp":
            return "image/webp"
        case "bmp":
            return "image/bmp"
        default:
            return nil
        }
    }

    /// Reads the image, enforces the size cap before decoding, verifies that AppKit can decode it, and returns a `data:` URL carrying the original bytes.
    static func imageDataURL(at url: URL) -> Result<String, FilePreviewImageError> {
        guard let mimeType = mimeType(forImageExtension: url.pathExtension) else {
            return .failure(.undecodable)
        }
        if let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
           let size = (attributes[.size] as? NSNumber)?.uint64Value,
           size > maximumImageBytes {
            return .failure(.tooLarge)
        }
        guard let data = try? Data(contentsOf: url) else {
            return .failure(.undecodable)
        }
        if UInt64(data.count) > maximumImageBytes {
            return .failure(.tooLarge)
        }
        guard NSImage(data: data) != nil else {
            return .failure(.undecodable)
        }
        return .success("data:\(mimeType);base64,\(data.base64EncodedString())")
    }
}
