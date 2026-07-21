import { readFileSync } from 'fs'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { defineConfig, loadEnv } from 'vite'
import viteCompression from 'vite-plugin-compression'
import { visualizer } from 'rollup-plugin-visualizer'

const packageJson = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version?: string }

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const appVersion = packageJson.version || ''
  
  const backendPort = env.PORT || '3000'
  const frontendPort = env.DEV_PORT || '3001'
  const fastapiPort = env.FASTAPI_PORT || '8900'
  const myselfAgentPort = env.MYSELF_AGENT_PORT || '8000'
  
  const isProduction = mode === 'production'

  return {
    plugins: [
      vue(),
      viteCompression({ algorithm: 'gzip', threshold: 10240 }),
      viteCompression({ algorithm: 'brotliCompress', threshold: 10240 }),
      ...(isProduction
        ? [
            visualizer({
              open: false,
              gzipSize: true,
              brotliSize: true,
              filename: 'dist/stats.html',
            }),
          ]
        : []),
    ],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    server: {
      host: '0.0.0.0',
      port: parseInt(String(frontendPort)),
      allowedHosts: true,
      proxy: {
        '/api': {
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
          // SSE 流式响应需要禁用缓冲
          configure: (proxy) => {
            proxy.on('proxyRes', (proxyRes) => {
              // 对于 SSE 响应，禁用代理缓冲
              if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
                proxyRes.headers['cache-control'] = 'no-cache'
                proxyRes.headers['x-accel-buffering'] = 'no'
              }
            })
          },
        },
        '/fastapi': {
          target: `http://localhost:${fastapiPort}`,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/fastapi/, ''),
        },
        '/myself-agent': {
          target: `http://localhost:${myselfAgentPort}`,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/myself-agent/, '/api/v1'),
        },
      },
    },
    build: {
      target: 'esnext',
      outDir: 'dist',
      ...(isProduction && {
        minify: 'esbuild' as const,
        esbuild: {
          drop: ['console', 'debugger'],
        },
      }),
      rollupOptions: {
        output: {
          manualChunks(id) {
            // Heavy vendor libraries → independent chunks for lazy loading
            if (id.includes('node_modules/phaser')) return 'phaser-vendor'
            if (id.includes('node_modules/vue-pdf-embed') || id.includes('node_modules/pdfjs-dist')) return 'pdf-vendor'
            if (id.includes('node_modules/@xterm') || id.includes('node_modules/xterm')) return 'xterm-vendor'
            if (id.includes('node_modules/markdown-it') || id.includes('node_modules/katex') || id.includes('node_modules/highlight.js') || id.includes('node_modules/highlightjs')) return 'markdown-vendor'
            if (id.includes('node_modules/naive-ui')) return 'naive-vendor'
            // Core framework
            if (id.includes('node_modules/vue/') || id.includes('node_modules/@vue/') ||
                id.includes('node_modules/vue-router') || id.includes('node_modules/pinia')) {
              return 'vue-vendor'
            }
          },
        },
      },
    },
    define: {
      'import.meta.env.VITE_APP_TITLE': JSON.stringify(env.VITE_APP_TITLE || 'OpenClaw Web'),
      'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion),
    },
  }
})
