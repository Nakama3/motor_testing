// swift-tools-version: 5.9

// WiFi Tracker - iPhone companion for the WiFi Heatmap web app.
// Open this folder (WiFiTracker.swiftpm) in Xcode, pick your iPhone, press Run.

import PackageDescription
import AppleProductTypes

let package = Package(
    name: "WiFiTracker",
    platforms: [
        .iOS("17.0")
    ],
    products: [
        .iOSApplication(
            name: "WiFi Tracker",
            targets: ["AppModule"],
            bundleIdentifier: "local.wifiheatmap.tracker",
            displayVersion: "1.0",
            bundleVersion: "1",
            accentColor: .presetColor(.blue),
            supportedDeviceFamilies: [
                .phone
            ],
            supportedInterfaceOrientations: [
                .portrait
            ],
            capabilities: [
                .camera(purposeString: "The camera is used by ARKit to track where you are as you walk through the house."),
                .localNetwork(purposeString: "Your position is sent to the WiFi Heatmap app running on your laptop.")
            ]
        )
    ],
    targets: [
        .executableTarget(
            name: "AppModule",
            path: "."
        )
    ]
)
