import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

const config = {
  preprocess: vitePreprocess(),
  kit: {
    // Disable prerendering so home data is fetched live at runtime instead of baked at build
    prerender: {
      entries: []
    },
    adapter: adapter({
      fallback: 'index.html',
      strict: false
    }),
    alias: {
      $components: 'src/lib/components',
      $stores: 'src/lib/stores',
      $api: 'src/lib/api'
    }
  }
};

export default config;
