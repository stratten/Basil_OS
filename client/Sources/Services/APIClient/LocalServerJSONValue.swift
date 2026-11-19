import Foundation

/// A JSON value the client passes through to the backend without interpreting it, such as a pasted setup recipe. The backend validates every field and the person approves every address and command it lists, so the client never needs to know the recipe's shape.
enum LocalServerJSONValue: Codable, Hashable {
    case null
    case bool(Bool)
    case integer(Int)
    case number(Double)
    case string(String)
    case array([LocalServerJSONValue])
    case object([String: LocalServerJSONValue])

    /// Converts what `JSONSerialization` produced (as the web bridge delivers it). Returns nil for a value JSON cannot hold.
    init?(any value: Any) {
        switch value {
        case is NSNull:
            self = .null
        case let text as String:
            self = .string(text)
        case let number as NSNumber:
            if CFGetTypeID(number) == CFBooleanGetTypeID() {
                self = .bool(number.boolValue)
            } else if CFNumberIsFloatType(number) {
                self = .number(number.doubleValue)
            } else {
                self = .integer(number.intValue)
            }
        case let items as [Any]:
            var converted: [LocalServerJSONValue] = []
            for item in items {
                guard let element = LocalServerJSONValue(any: item) else { return nil }
                converted.append(element)
            }
            self = .array(converted)
        case let fields as [String: Any]:
            var converted: [String: LocalServerJSONValue] = [:]
            for (key, item) in fields {
                guard let element = LocalServerJSONValue(any: item) else { return nil }
                converted[key] = element
            }
            self = .object(converted)
        default:
            return nil
        }
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .integer(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([LocalServerJSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: LocalServerJSONValue].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .integer(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }
}
