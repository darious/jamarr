import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [
    tailwindcss(),
    sveltekit({
      preprocess: vitePreprocess(),
      // Disable prerendering so home data is fetched live at runtime instead of baked at build
      prerender: {
        entries: []
      },
      adapter: adapter({
        fallback: 'index.html',
        strict: false
      }),
      alias: {
        // Kit 3 replaced $lib with the #lib import map; keep the old alias
        $lib: 'src/lib',
        $components: 'src/lib/components',
        $stores: 'src/lib/stores',
        $api: 'src/lib/api'
      }
    })
  ],
  ssr: {
    noExternal: ['layercake']
  },
  optimizeDeps: {
    include: ['layercake']
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8111',
        changeOrigin: true,
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            // Add X-Forwarded-For header with the real client IP
            const clientIp = req.socket.remoteAddress || req.connection.remoteAddress;
            if (clientIp) {
              proxyReq.setHeader('X-Forwarded-For', clientIp);
              proxyReq.setHeader('X-Real-IP', clientIp);
            }
          });
        }
      },
      '^/art(/|$)': {
        target: 'http://127.0.0.1:8111',
        changeOrigin: true,
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            const clientIp = req.socket.remoteAddress || req.connection.remoteAddress;
            if (clientIp) {
              proxyReq.setHeader('X-Forwarded-For', clientIp);
              proxyReq.setHeader('X-Real-IP', clientIp);
            }
          });
        }
      }
    }
  }
});
