import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  css: {
    postcss: {
      plugins: [],
    },
  },
  server: {
    port: 5173,
    strictPort: false,
  },
  build: {
    target: 'esnext',
    outDir: 'dist',
    sourcemap: false,
  },
});
