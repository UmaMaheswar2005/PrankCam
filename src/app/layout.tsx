import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "PrankCam", description: "Real-time face swap" };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;700&display=swap" rel="stylesheet" />
      </head>
      <body className="antialiased" style={{ fontFamily: "'IBM Plex Mono', monospace" }}>{children}</body>
    </html>
  );
}
