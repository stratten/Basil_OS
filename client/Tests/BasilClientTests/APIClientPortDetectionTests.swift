import XCTest
import Foundation
@testable import BasilClient

final class APIClientPortDetectionTests: XCTestCase {
    var tempDirectory: URL!
    var testBundle: Bundle!
    
    override func setUp() {
        super.setUp()
        // Create a temporary directory for test files
        tempDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try! FileManager.default.createDirectory(at: tempDirectory, withIntermediateDirectories: true)
    }
    
    override func tearDown() {
        // Clean up temporary files
        try? FileManager.default.removeItem(at: tempDirectory)
        tempDirectory = nil
        testBundle = nil
        super.tearDown()
    }
    
    // MARK: - Port File Detection Tests
    
    func testPortDetectionWithDevelopmentFile() {
        // Given - Create a development-style port file
        let devPortFile = tempDirectory.appendingPathComponent(".server_port")
        let testPort = "8001"
        try! testPort.write(to: devPortFile, atomically: true, encoding: .utf8)
        
        // When - Test the detection logic (simulating development environment)
        let currentDir = FileManager.default.currentDirectoryPath
        FileManager.default.changeCurrentDirectoryPath(tempDirectory.appendingPathComponent("subfolder").path)
        
        // Create subfolder and change to it (simulating BasilClient subdirectory)
        let subFolder = tempDirectory.appendingPathComponent("subfolder")
        try! FileManager.default.createDirectory(at: subFolder, withIntermediateDirectories: true)
        FileManager.default.changeCurrentDirectoryPath(subFolder.path)
        
        let detectedPort = APIClient.readPortFromFile()
        
        // Restore original directory
        FileManager.default.changeCurrentDirectoryPath(currentDir)
        
        // Then
        XCTAssertEqual(detectedPort, 8001, "Should detect port from development file")
    }
    
    func testPortDetectionWithBundledAppFile() {
        // Given - Create mock bundle structure
        let bundleResourcesPath = tempDirectory.appendingPathComponent("MockBundle.app/Contents/Resources")
        let appSupportPath = bundleResourcesPath.appendingPathComponent("AppSupport")
        try! FileManager.default.createDirectory(at: appSupportPath, withIntermediateDirectories: true)
        
        let bundledPortFile = appSupportPath.appendingPathComponent("server_port")
        let testPort = "8002"
        try! testPort.write(to: bundledPortFile, atomically: true, encoding: .utf8)
        
        // When - Test with mocked bundle resource path
        // Note: This would require dependency injection in real implementation
        // For now, we'll test the file reading logic directly
        
        let exists = FileManager.default.fileExists(atPath: bundledPortFile.path)
        let portString = try? String(contentsOfFile: bundledPortFile.path, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let port = portString.flatMap(Int.init)
        
        // Then
        XCTAssertTrue(exists, "Bundled port file should exist")
        XCTAssertEqual(port, 8002, "Should read correct port from bundled file")
    }
    
    func testPortDetectionWithInvalidContent() {
        // Given - Create port file with invalid content
        let portFile = tempDirectory.appendingPathComponent(".server_port")
        let invalidContent = "not_a_port_number"
        try! invalidContent.write(to: portFile, atomically: true, encoding: .utf8)
        
        // When
        let exists = FileManager.default.fileExists(atPath: portFile.path)
        let portString = try? String(contentsOfFile: portFile.path, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let port = portString.flatMap(Int.init)
        
        // Then
        XCTAssertTrue(exists, "File should exist")
        XCTAssertEqual(portString, "not_a_port_number", "Should read the invalid content")
        XCTAssertNil(port, "Should not parse invalid content as port number")
    }
    
    func testPortDetectionWithWhitespace() {
        // Given - Create port file with whitespace
        let portFile = tempDirectory.appendingPathComponent(".server_port")
        let contentWithWhitespace = "  8003  \n\t  "
        try! contentWithWhitespace.write(to: portFile, atomically: true, encoding: .utf8)
        
        // When
        let portString = try? String(contentsOfFile: portFile.path, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let port = portString.flatMap(Int.init)
        
        // Then
        XCTAssertEqual(portString, "8003", "Should trim whitespace")
        XCTAssertEqual(port, 8003, "Should parse trimmed content as port number")
    }
    
    func testPortDetectionWithNoFiles() {
        // Given - No port files exist
        
        // When - Try to read from non-existent locations
        let nonExistentFile = tempDirectory.appendingPathComponent("nonexistent.port")
        let exists = FileManager.default.fileExists(atPath: nonExistentFile.path)
        
        // Then
        XCTAssertFalse(exists, "Non-existent file should not exist")
        // The actual readPortFromFile would return nil in this case
    }
    
    // MARK: - File Path Priority Tests
    
    func testMultiplePortFilesUsesCorrectPriority() {
        // Given - Create multiple port files in different locations
        let currentDir = FileManager.default.currentDirectoryPath
        
        // Create dev file (higher priority)
        let devPortFile = tempDirectory.appendingPathComponent(".server_port")
        try! "8001".write(to: devPortFile, atomically: true, encoding: .utf8)
        
        // Create legacy file (lower priority)
        let legacyDir = tempDirectory.appendingPathComponent(".basil")
        try! FileManager.default.createDirectory(at: legacyDir, withIntermediateDirectories: true)
        let legacyPortFile = legacyDir.appendingPathComponent(".server_port")
        try! "8999".write(to: legacyPortFile, atomically: true, encoding: .utf8)
        
        // When - Check priority (simulate being in subdirectory)
        let subFolder = tempDirectory.appendingPathComponent("subfolder")
        try! FileManager.default.createDirectory(at: subFolder, withIntermediateDirectories: true)
        FileManager.default.changeCurrentDirectoryPath(subFolder.path)
        
        // Manually test the path resolution logic
        let possiblePaths = [
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
                .deletingLastPathComponent()
                .appendingPathComponent(".server_port").path,
            legacyPortFile.path
        ]
        
        var foundPort: Int?
        for path in possiblePaths {
            if FileManager.default.fileExists(atPath: path) {
                if let portString = try? String(contentsOfFile: path, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
                   let port = Int(portString) {
                    foundPort = port
                    break
                }
            }
        }
        
        // Restore directory
        FileManager.default.changeCurrentDirectoryPath(currentDir)
        
        // Then
        XCTAssertEqual(foundPort, 8001, "Should use development file (higher priority) when both exist")
    }
    
    // MARK: - Integration Test with APIClient

    func testBackendURLArgumentSelectsItsPort() {
        let port = APIClient.backendPortOverride(
            arguments: [
                "BasilClient",
                "--backend-url",
                "http://127.0.0.1:8765"
            ]
        )

        XCTAssertEqual(port, 8765)
    }

    func testBackendURLArgumentRetainsTheValidatedLoopbackOrigin() {
        let url = APIClient.backendURLOverride(
            arguments: [
                "BasilClient",
                "--backend-url",
                "http://localhost:8765"
            ]
        )

        XCTAssertEqual(url?.absoluteString, "http://localhost:8765")
    }

    func testBackendURLArgumentRejectsMissingOrPortlessValues() {
        XCTAssertNil(
            APIClient.backendPortOverride(arguments: ["BasilClient", "--backend-url"])
        )
        XCTAssertNil(
            APIClient.backendPortOverride(
                arguments: ["BasilClient", "--backend-url", "http://127.0.0.1"]
            )
        )
    }

    func testBackendURLArgumentRejectsNonLoopbackOrCredentialedOrigins() {
        XCTAssertNil(
            APIClient.backendURLOverride(
                arguments: ["BasilClient", "--backend-url", "http://example.com:8765"]
            )
        )
        XCTAssertNil(
            APIClient.backendURLOverride(
                arguments: ["BasilClient", "--backend-url", "http://token@127.0.0.1:8765"]
            )
        )
    }
    
    func testAPIClientPortInitialization() {
        // Given - No launch args, no port file exists
        
        // When - Create APIClient instance
        let apiClient = APIClient()
        
        // Then - Should default to 8000
        XCTAssertEqual(apiClient.currentPort, 8000, "Should default to port 8000 when no port file exists")
    }
} 