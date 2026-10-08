// swift-tools-version: 5.9
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "BasilClient",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(
            name: "BasilClient",
            targets: ["BasilClient"]
        ),
    ],
    dependencies: [
        .package(url: "https://github.com/soffes/HotKey", from: "0.2.0"),
        .package(url: "https://github.com/sparkle-project/Sparkle", from: "2.9.6")
    ],
    targets: [
        .executableTarget(
            name: "BasilClient",
            dependencies: [
                "HotKey",
                "Sparkle"
            ],
            path: "Sources",
            exclude: ["Support/Info.plist", "Support/ValidationInfo.plist", "Support/Basil.entitlements"],
            resources: [
                .process("Resources")
            ],
            swiftSettings: [
                .define("DEBUG", .when(configuration: .debug))
            ]
        ),
        .testTarget(
            name: "BasilClientTests",
            dependencies: ["BasilClient"],
            path: "Tests",
            exclude: ["Manual"]
        ),
    ]
)
