/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Isolate the charting library in its own async chunk (Requirement 14.1)
        // WITHOUT dragging shared dependencies (notably React) into it. A plain
        // `manualChunks: { charts: ["recharts"] }` group anchors the chunk on
        // recharts and pulls React in too, which then forces the initial index
        // chunk to statically import that large chunk — defeating lazy-loading.
        //
        // The function form scopes the chunk to recharts and the packages only
        // it uses (its d3/victory-vendor transitive deps), so React stays in the
        // shared/initial graph and the charts chunk is reached solely through the
        // `React.lazy` chart imports — absent from the initial paint (Req 14.1)
        // and never fetched on chart-free screens (Req 14.2).
        manualChunks(id) {
          // Anchor React (and react-dom) to a shared vendor chunk that lives in
          // the initial graph. Without this, forcing recharts into its own chunk
          // lets Rollup hoist shared React into the charts chunk and then makes
          // the initial index chunk statically import it back — eagerly loading
          // the whole charting chunk and defeating lazy-loading (Req 14.1).
          if (
            /node_modules\/(react|react-dom|scheduler|react-is|prop-types|clsx)\//.test(
              id,
            )
          ) {
            return "react-vendor";
          }
          // Isolate the charting library and the packages only it uses (its
          // d3 / victory-vendor transitive deps) in a separate async chunk. It
          // is reached solely through the `React.lazy` chart imports, so it is
          // absent from the initial paint (Req 14.1) and never fetched on
          // chart-free screens (Req 14.2).
          if (
            /node_modules\/(recharts|victory-vendor|d3-[^/]+|internmap|recharts-scale|decimal\.js-light)\//.test(
              id,
            )
          ) {
            return "charts";
          }
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
});
