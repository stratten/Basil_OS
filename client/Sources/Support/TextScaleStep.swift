import Foundation

/// The app-wide text size steps and the pure arithmetic over them.
///
/// The five steps (90%, 100%, 110%, 125%, 140%) mirror `TEXT_SCALE_STEPS` in the backend preference model. A stored or
/// received value that is not one of them is snapped to the nearest step, and anything that is not a finite number
/// means 100%, so a hand-edited preference or a stale payload can never put the app at an unreadable size.
enum TextScaleStep {
    static let steps: [Double] = [0.9, 1.0, 1.1, 1.25, 1.4]
    static let defaultScale: Double = 1.0

    /// The offered step nearest to `value`; an exact tie prefers the smaller step, and a non-finite value means 100%.
    static func snapped(_ value: Double) -> Double {
        guard value.isFinite else { return defaultScale }
        return steps.min { lhs, rhs in
            let lhsDistance = abs(lhs - value)
            let rhsDistance = abs(rhs - value)
            return lhsDistance == rhsDistance ? lhs < rhs : lhsDistance < rhsDistance
        } ?? defaultScale
    }

    /// The next larger step after the step nearest to `current`, or the largest step when already there.
    static func larger(than current: Double) -> Double {
        let snappedCurrent = snapped(current)
        return steps.first { $0 > snappedCurrent } ?? steps[steps.count - 1]
    }

    /// The next smaller step before the step nearest to `current`, or the smallest step when already there.
    static func smaller(than current: Double) -> Double {
        let snappedCurrent = snapped(current)
        return steps.last { $0 < snappedCurrent } ?? steps[0]
    }

    /// The label of a step as a whole percentage, such as "125%".
    static func percentLabel(for scale: Double) -> String {
        "\(Int((snapped(scale) * 100).rounded()))%"
    }

    /// Source of the document-start user script that sets `--text-scale` on the root element before the page's first paint, so no window flashes at the wrong size while the bridge theme is still on its way. When the root element does not exist yet it waits for it.
    nonisolated static func firstPaintScriptSource(scale: Double) -> String {
        let literal = String(format: "%g", snapped(scale))
        return "(function(){var v='\(literal)';function a(){var r=document.documentElement;if(!r)return false;r.style.setProperty('--text-scale',v);return true;}if(!a()){var o=new MutationObserver(function(){if(a())o.disconnect();});o.observe(document,{childList:true});}})();"
    }
}
