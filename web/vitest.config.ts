import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
    test: {
        environment: 'jsdom',
        include: ['src/**/*.test.ts'],
        globals: false,
    },
    resolve: {
        alias: {
            $lib: path.resolve(root, 'src/lib'),
            $components: path.resolve(root, 'src/lib/components'),
            $stores: path.resolve(root, 'src/lib/stores'),
            $api: path.resolve(root, 'src/lib/api'),
        },
    },
});
