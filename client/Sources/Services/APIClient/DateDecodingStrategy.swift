import Foundation

extension JSONDecoder.DateDecodingStrategy {
    /// Custom ISO8601 date decoding strategy that handles multiple formats
    ///
    /// This strategy tries multiple date formats in order:
    /// 1. Standard ISO8601 with fractional seconds
    /// 2. ISO8601 without fractional seconds
    /// 3. Custom format with microseconds (Python datetime default)
    /// 4. ISO8601 with 'Z' timezone indicator
    ///
    /// This ensures compatibility with various backend datetime serialization formats.
    static let customISO8601 = custom { decoder in
        let container = try decoder.singleValueContainer()
        let dateString = try container.decode(String.self)
        
        // Try standard ISO8601 with fractional seconds first
        let iso8601Formatter = ISO8601DateFormatter()
        iso8601Formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = iso8601Formatter.date(from: dateString) {
            return date
        }
        
        // Try ISO8601 without fractional seconds
        iso8601Formatter.formatOptions = [.withInternetDateTime]
        if let date = iso8601Formatter.date(from: dateString) {
            return date
        }
        
        // Try custom format with microseconds (Python datetime default)
        let microsecondsFormatter = DateFormatter()
        microsecondsFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        microsecondsFormatter.timeZone = TimeZone(secondsFromGMT: 0)
        microsecondsFormatter.locale = Locale(identifier: "en_US_POSIX")
        if let date = microsecondsFormatter.date(from: dateString) {
            return date
        }
        
        // Try format with 'Z' timezone indicator (our standard format)
        let zFormatter = DateFormatter()
        zFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss'Z'"
        zFormatter.timeZone = TimeZone(secondsFromGMT: 0)
        zFormatter.locale = Locale(identifier: "en_US_POSIX")
        if let date = zFormatter.date(from: dateString) {
            return date
        }
        
        // Try format without timezone indicator
        let noTzFormatter = DateFormatter()
        noTzFormatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        noTzFormatter.timeZone = TimeZone(secondsFromGMT: 0)
        noTzFormatter.locale = Locale(identifier: "en_US_POSIX")
        if let date = noTzFormatter.date(from: dateString) {
            return date
        }
        
        throw DecodingError.dataCorruptedError(
            in: container,
            debugDescription: "Cannot decode date from string: \(dateString). Expected ISO8601 format."
        )
    }
}

