import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "UW Kabel-Master ToolUI by Jens",
        short_name: "UW Kabel-Master",
        description: "Kabelzug und Listen - auch offline",
        lang: "de",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "any",
        background_color: "#0f1720",
        theme_color: "#0f1720",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        // App-Shell offline verfügbar; API-Aufrufe laufen nie über den Cache (Offline-Daten liegen in IndexedDB)
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        globPatterns: ["**/*.{js,css,html,svg,png,webmanifest}"],
      },
    }),
  ],
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
