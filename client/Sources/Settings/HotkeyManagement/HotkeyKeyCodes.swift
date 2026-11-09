import Foundation

/// ANSI virtual key codes for the keys a Basil hotkey can use, so a binding can be compared with the key codes macOS stores for its own shortcuts. A key that is not listed has no code and cannot match a stored macOS shortcut.
enum HotkeyKeyCodes {
    private static let codes: [String: Int] = [
        "A": 0, "S": 1, "D": 2, "F": 3, "H": 4, "G": 5, "Z": 6, "X": 7, "C": 8, "V": 9,
        "B": 11, "Q": 12, "W": 13, "E": 14, "R": 15, "Y": 16, "T": 17,
        "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29,
        "O": 31, "U": 32, "I": 34, "P": 35, "L": 37, "J": 38, "K": 40, "N": 45, "M": 46,
        "SPACE": 49,
        "F1": 122, "F2": 120, "F3": 99, "F4": 118, "F5": 96, "F6": 97,
        "F7": 98, "F8": 100, "F9": 101, "F10": 109, "F11": 103, "F12": 111,
    ]

    private static let functionKeys: Set<String> = [
        "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    ]

    static func code(for key: String) -> Int? {
        codes[key.trimmingCharacters(in: .whitespaces).uppercased()]
    }

    /// True for F1 to F12, which act as media keys on a Mac that has not been set to use them as standard function keys.
    static func isFunctionKey(_ key: String) -> Bool {
        functionKeys.contains(key.trimmingCharacters(in: .whitespaces).uppercased())
    }
}
