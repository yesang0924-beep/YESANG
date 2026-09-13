import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { viteSingleFile } from 'vite-plugin-singlefile'

export default defineConfig({
  // viteSingleFile 把 JS/CSS 全部内联进 index.html。
  // 原因：产物由 pywebview 以 file:// 加载，而 Vite 默认会给 <script type="module">
  // 加 crossorigin —— 在 file:// 协议下会被 Chromium 按 CORS 拒绝，导致白屏。
  // 内联成单文件后没有任何外部资源请求，从根上避开这个坑。
  plugins: [vue(), viteSingleFile()],
  base: './',
  build: {
    // 输出到 ../web；app.py 与 PyInstaller 的 datas 都指向这里。
    // 刻意避开 PyInstaller 自己的 dist/（官方文档特别提醒过）。
    outDir: '../web',
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 100000000,
    sourcemap: false,
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
})
