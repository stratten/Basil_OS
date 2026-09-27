import Foundation
import AppKit

// MARK: - Widget Size Type

/// Type-safe wrapper for widget dimensions that encodes/decodes as JSON array
struct WidgetSize: Codable, Equatable, Hashable {
    let width: Int
    let height: Int
    
    init(width: Int, height: Int) {
        self.width = width
        self.height = height
    }
    
    init(from decoder: Decoder) throws {
        var container = try decoder.unkeyedContainer()
        width = try container.decode(Int.self)
        height = try container.decode(Int.self)
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.unkeyedContainer()
        try container.encode(width)
        try container.encode(height)
    }
    
    /// Convert to array format for API compatibility
    var asArray: [Int] { [width, height] }
    
    /// Convert to NSSize for UI operations
    var asNSSize: NSSize { NSSize(width: width, height: height) }
    
    /// Create from NSSize
    init(nsSize: NSSize) {
        self.width = Int(nsSize.width)
        self.height = Int(nsSize.height)
    }
}

// MARK: - Widget Position Type

/// Type-safe wrapper for widget position with screen ID that encodes/decodes as JSON array
struct WidgetPosition: Codable, Equatable, Hashable {
    let x: Double
    let y: Double
    let screenID: Int
    
    init(x: Double, y: Double, screenID: Int) {
        self.x = x
        self.y = y
        self.screenID = screenID
    }
    
    init(from decoder: Decoder) throws {
        var container = try decoder.unkeyedContainer()
        x = try container.decode(Double.self)
        y = try container.decode(Double.self)
        screenID = try container.decode(Int.self)
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.unkeyedContainer()
        try container.encode(x)
        try container.encode(y)
        try container.encode(screenID)
    }
    
    /// Convert to array format for API compatibility
    var asArray: [Double] { [x, y, Double(screenID)] }
    
    /// Convert to NSPoint (ignoring screen ID)
    var asNSPoint: NSPoint { NSPoint(x: x, y: y) }
    
    /// Create from NSPoint with screen ID
    init(nsPoint: NSPoint, screenID: Int) {
        self.x = nsPoint.x
        self.y = nsPoint.y
        self.screenID = screenID
    }
}

