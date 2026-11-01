import XCTest
@testable import BasilClient

/// Pins the behavior of `DateFormattingUtils` after its formatters became shared and immutable, by comparing against freshly constructed reference formatters.
final class DateFormattingUtilsTests: XCTestCase {
    private func referenceLocalDate(_ text: String, format: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .current
        formatter.dateFormat = format
        return formatter.date(from: text)
    }

    private func referenceUTCDate(_ text: String, format: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = format
        return formatter.date(from: text)
    }

    func testInternetDateTimeParsesTimezoneQualifiedTimestampsWithAndWithoutFractionalSeconds() {
        let fractional = DateFormattingUtils.parseInternetDateTime("2026-01-23T10:17:41.213Z")
        let whole = DateFormattingUtils.parseInternetDateTime("2026-01-23T10:17:41Z")
        let offset = DateFormattingUtils.parseInternetDateTime("2026-01-23T05:17:41-05:00")

        XCTAssertEqual(fractional?.timeIntervalSince1970 ?? 0, 1_769_163_461.213, accuracy: 0.001)
        XCTAssertEqual(whole?.timeIntervalSince1970, 1_769_163_461)
        XCTAssertEqual(offset?.timeIntervalSince1970, 1_769_163_461)
    }

    func testInternetDateTimeRejectsTimezoneLessAndMalformedText() {
        XCTAssertNil(DateFormattingUtils.parseInternetDateTime("2026-01-23T10:17:41.213599"))
        XCTAssertNil(DateFormattingUtils.parseInternetDateTime("2026-01-23"))
        XCTAssertNil(DateFormattingUtils.parseInternetDateTime(""))
        XCTAssertNil(DateFormattingUtils.parseInternetDateTime("not a date"))
    }

    func testParseISO8601MatchesReferenceForEveryAcceptedShape() {
        XCTAssertEqual(
            DateFormattingUtils.parseISO8601("2026-01-23T10:17:41.213599"),
            referenceLocalDate("2026-01-23T10:17:41.213599", format: "yyyy-MM-dd'T'HH:mm:ss.SSSSSS")
        )
        XCTAssertEqual(
            DateFormattingUtils.parseISO8601("2026-01-23T10:17:41.213"),
            referenceLocalDate("2026-01-23T10:17:41.213", format: "yyyy-MM-dd'T'HH:mm:ss.SSS")
        )
        XCTAssertEqual(
            DateFormattingUtils.parseISO8601("2026-01-23T10:17:41"),
            referenceLocalDate("2026-01-23T10:17:41", format: "yyyy-MM-dd'T'HH:mm:ss")
        )
        XCTAssertEqual(
            DateFormattingUtils.parseISO8601("2026-01-23"),
            referenceLocalDate("2026-01-23", format: "yyyy-MM-dd")
        )
        XCTAssertEqual(
            DateFormattingUtils.parseISO8601("2026-06-29 14:45:00"),
            referenceUTCDate("2026-06-29 14:45:00", format: "yyyy-MM-dd HH:mm:ss")
        )
        XCTAssertEqual(
            DateFormattingUtils.parseISO8601("2026-06-29 14:45:00.125"),
            referenceUTCDate("2026-06-29 14:45:00.125", format: "yyyy-MM-dd HH:mm:ss.SSS")
        )
        XCTAssertEqual(DateFormattingUtils.parseISO8601("2026-01-23T10:17:41Z")?.timeIntervalSince1970, 1_769_163_461)
    }

    func testParseISO8601ReturnsNilForUnparseableText() {
        XCTAssertNil(DateFormattingUtils.parseISO8601(""))
        XCTAssertNil(DateFormattingUtils.parseISO8601("yesterday"))
        XCTAssertNil(DateFormattingUtils.parseISO8601("2026-13-45T99:99:99"))
    }

    func testSidebarFormatMatchesReferenceFormatter() {
        let reference = DateFormatter()
        reference.dateFormat = "yyyy-MM-dd h:mm a"
        reference.amSymbol = "am"
        reference.pmSymbol = "pm"
        reference.timeZone = .current

        for offset in [0.0, 3_600.0, 43_200.0, 86_400.0 * 40, 86_400.0 * 400] {
            let date = Date(timeIntervalSince1970: 1_769_163_461 + offset)
            XCTAssertEqual(DateFormattingUtils.sidebarFormat(date), reference.string(from: date))
        }
    }

    func testRelativeFormatCoversTodayYesterdayAndOlderBranches() {
        let now = Date()
        let timeReference = DateFormatter()
        timeReference.timeStyle = .short

        XCTAssertEqual(DateFormattingUtils.relativeFormat(now), "Today, \(timeReference.string(from: now))")

        let yesterday = Calendar.current.date(byAdding: .day, value: -1, to: now)!
        XCTAssertEqual(DateFormattingUtils.relativeFormat(yesterday), "Yesterday, \(timeReference.string(from: yesterday))")

        let old = Date(timeIntervalSince1970: 1_600_000_000)
        let monthReference = DateFormatter()
        monthReference.dateFormat = "MMM d, h:mm a"
        XCTAssertEqual(DateFormattingUtils.relativeFormat(old), monthReference.string(from: old))
    }

    func testFormatTimestampReturnsRawTextWhenUnparseable() {
        XCTAssertEqual(DateFormattingUtils.formatTimestamp("not a date", style: .absolute), "not a date")
        XCTAssertEqual(DateFormattingUtils.formatTimestamp("not a date", style: .relative), "not a date")
    }

    func testSharedFormattersGiveIdenticalResultsUnderConcurrentUse() {
        let timestamps = [
            "2026-01-23T10:17:41.213Z",
            "2026-01-23T10:17:41.213599",
            "2026-01-23T10:17:41",
            "2026-06-29 14:45:00",
            "2026-01-23"
        ]
        let expected = timestamps.map { DateFormattingUtils.formatTimestamp($0, style: .absolute) }
        let lock = NSLock()
        var mismatches = 0

        DispatchQueue.concurrentPerform(iterations: 400) { iteration in
            let index = iteration % timestamps.count
            let actual = DateFormattingUtils.formatTimestamp(timestamps[index], style: .absolute)
            if actual != expected[index] {
                lock.lock()
                mismatches += 1
                lock.unlock()
            }
        }

        XCTAssertEqual(mismatches, 0)
    }

    func testSharedFormattersAreFasterThanConstructingFormattersPerValue() {
        let timestamps = (0..<50).map { "2026-01-\(String(format: "%02d", ($0 % 28) + 1))T10:17:41.213Z" }

        func milliseconds(_ work: () -> Void) -> Double {
            let start = DispatchTime.now()
            work()
            return Double(DispatchTime.now().uptimeNanoseconds - start.uptimeNanoseconds) / 1_000_000
        }

        // Warm one-time costs (locale data, lazy statics) so neither side pays them inside the measurement.
        _ = DateFormattingUtils.formatTimestamp(timestamps[0], style: .absolute)
        _ = DateFormattingUtils.formatTimestamp(timestamps[0], style: .relative)

        let shared = milliseconds {
            for _ in 0..<20 {
                for timestamp in timestamps {
                    _ = DateFormattingUtils.formatTimestamp(timestamp, style: .absolute)
                    _ = DateFormattingUtils.formatTimestamp(timestamp, style: .relative)
                }
            }
        }

        // The pre-change cost model: a new ISO8601 formatter and a new DateFormatter for every value formatted.
        let constructedPerValue = milliseconds {
            for _ in 0..<20 {
                for timestamp in timestamps {
                    for format in ["yyyy-MM-dd h:mm a", "MMM d, h:mm a"] {
                        let parser = ISO8601DateFormatter()
                        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                        let formatter = DateFormatter()
                        formatter.dateFormat = format
                        _ = parser.date(from: timestamp).map(formatter.string(from:))
                    }
                }
            }
        }

        XCTAssertLessThan(shared * 2, constructedPerValue, "shared \(shared) ms vs per-value construction \(constructedPerValue) ms")
    }
}
