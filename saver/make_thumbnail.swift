// Generates thumbnail.png (90x58) and thumbnail@2x.png (180x116). Run: swift make_thumbnail.swift
import AppKit
let rows = ["....#......","...###.....","..#####....","..#####....",".#######...",".#.###.#...","#..###..#..","...#.#.....","..#...#...."]
func render(_ w: Int, _ h: Int, _ path: String) {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8,
        samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSColor(srgbRed: 0xE9/255, green: 0xE7/255, blue: 0xE0/255, alpha: 1).setFill()
    NSRect(x: 0, y: 0, width: w, height: h).fill()
    NSColor(srgbRed: 0x1B/255, green: 0x1B/255, blue: 0x1A/255, alpha: 1).setFill()
    let px = h / 14, ox = (w - 11 * px) / 2, oy = (h - 9 * px) / 2
    for (y, r) in rows.enumerated() { for (x, c) in r.enumerated() where c == "#" {
        NSRect(x: ox + x * px, y: oy + (8 - y) * px, width: px, height: px).fill() } }
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
}
render(90, 58, "thumbnail.png"); render(180, 116, "thumbnail@2x.png")
