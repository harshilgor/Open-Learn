// Isolated visual QA of the real quiz components with synthetic content.
import { createServer } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
const server = await createServer({ root, configFile: false, plugins: [react()],
  resolve: { alias: { '@': root } }, server: { host: '127.0.0.1', port: 5288, strictPort: true } });
await server.listen();
server.printUrls();
