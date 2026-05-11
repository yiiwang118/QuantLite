import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'
import path from 'node:path'

export default defineConfig({
  plugins: [
    vue(),
    Components({
      resolvers: [NaiveUiResolver()],
      dts: false,
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('echarts') || id.includes('vue-echarts') || id.includes('zrender')) {
            return 'vendor-echarts'
          }
          if (id.includes('naive-ui') || id.includes('vooks') || id.includes('vueuc')
              || id.includes('css-render') || id.includes('seemly') || id.includes('treemate')
              || id.includes('@css-render') || id.includes('evtd') || id.includes('async-validator')
              || id.includes('vdirs')) {
            return 'vendor-naive'
          }
          if (id.includes('marked') || id.includes('dompurify')) {
            return 'vendor-md'
          }
          if (id.includes('@vicons')) {
            return 'vendor-icons'
          }
          if (id.includes('vue-i18n') || id.includes('@intlify')) {
            return 'vendor-i18n'
          }
          if (id.includes('vue/') || id.includes('vue-router') || id.includes('pinia')
              || id.includes('@vue/')) {
            return 'vendor-vue'
          }
          if (id.includes('axios') || id.includes('dayjs')) {
            return 'vendor-utils'
          }
        },
      },
    },
  },
})
