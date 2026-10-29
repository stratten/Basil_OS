import AppKit
import Foundation
import SwiftUI

struct ModelDownloadPanelSnapshot {
    struct Row {
        let modelId: String
        let status: String
        let progress: Double
        let totalDownloaded: Int64?
        let totalSize: Int64?
        let isRetrying: Bool

        var jsonObject: [String: Any] {
            [
                "modelId": modelId,
                "status": status,
                "progress": progress,
                "totalDownloaded": totalDownloaded.map(NSNumber.init(value:)) ?? NSNull(),
                "totalSize": totalSize.map(NSNumber.init(value:)) ?? NSNull(),
                "isRetrying": isRetrying,
            ]
        }
    }

    let phaseMessage: String
    let isComplete: Bool
    let quantizedPercentage: Int
    let appIconDataUrl: String?
    let models: [Row]

    func jsonObject(includeAppIcon: Bool = true) -> [String: Any] {
        var payload: [String: Any] = [
            "phaseMessage": phaseMessage,
            "isComplete": isComplete,
            "quantizedPercentage": quantizedPercentage,
            "models": models.map(\.jsonObject),
        ]
        if includeAppIcon {
            payload["appIconDataUrl"] = appIconDataUrl ?? NSNull()
        }
        return payload
    }
}

enum ModelDownloadMiniPanelTheme {
    static func themePayload() -> [String: Any] {
        AestheticWebPayload.themePayload()
    }

    static func appIconDataUrl() -> String? {
        guard let tiff = NSApp.applicationIconImage.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            return nil
        }
        return "data:image/png;base64,\(png.base64EncodedString())"
    }
}
