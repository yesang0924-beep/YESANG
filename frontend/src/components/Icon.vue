<script setup>
/**
 * 轻量线性图标集（24×24 viewBox，stroke 风格，跟随 currentColor）。
 * 不引第三方图标库：几十个路径而已，内联进来零依赖、零网络请求。
 */
const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 16 },
  strokeWidth: { type: [Number, String], default: 1.75 },
})

const PATHS = {
  /* 状态 */
  check: ['M20 6L9 17l-5-5'],
  alert: ['M12 9v4', 'M12 17h.01', 'M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'],
  close: ['M18 6L6 18', 'M6 6l12 12'],
  info: ['M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20', 'M12 16v-4', 'M12 8h.01'],

  /* 操作 */
  refresh: ['M23 4v6h-6', 'M1 20v-6h6',
            'M3.51 9a9 9 0 0 1 14.85-3.36L23 10', 'M1 14l4.64 4.36A9 9 0 0 0 20.49 15'],
  play: ['M6 4l13 8-13 8V4z'],
  stop: ['M6 6h12v12H6z'],
  power: ['M18.36 6.64a9 9 0 1 1-12.73 0', 'M12 2v10'],
  pencil: ['M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7',
           'M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z'],
  trash: ['M3 6h18', 'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6',
          'M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'],
  zap: ['M13 2L3 14h9l-1 8 10-12h-9l1-8z'],
  plus: ['M12 5v14', 'M5 12h14'],
  folder: ['M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z'],

  /* 导航 */
  chevron: ['M9 18l6-6-6-6'],
  sun: ['M12 4a8 8 0 1 0 0 16a8 8 0 1 0 0-16', 'M12 1v2', 'M12 21v2',
        'M4.22 4.22l1.42 1.42', 'M18.36 18.36l1.42 1.42',
        'M1 12h2', 'M21 12h2', 'M4.22 19.78l1.42-1.42', 'M18.36 5.64l1.42-1.42'],
  moon: ['M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z'],

  /* 领域图标 */
  activity: ['M22 12h-4l-3 9L9 3l-3 9H2'],
  server: ['M4 3h16a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z',
           'M4 14h16a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5a1 1 0 0 1 1-1z',
           'M7 6h.01', 'M7 17h.01'],
  globe: ['M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20', 'M2 12h20',
          'M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z'],
  shield: ['M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'],
  terminal: ['M4 17l6-6-6-6', 'M12 19h8'],
  database: ['M12 2C7.58 2 4 3.79 4 6v12c0 2.21 3.58 4 8 4s8-1.79 8-4V6c0-2.21-3.58-4-8-4z',
             'M4 6c0 2.21 3.58 4 8 4s8-1.79 8-4', 'M4 12c0 2.21 3.58 4 8 4s8-1.79 8-4'],
  layers: ['M12 2L2 7l10 5 10-5-10-5z', 'M2 17l10 5 10-5', 'M2 12l10 5 10-5'],
  gauge: ['M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
          'M13.4 10.6L19 5', 'M12 2a10 10 0 0 1 8.66 15H3.34A10 10 0 0 1 12 2z'],
  route: ['M6 3v12a3 3 0 1 0 6 0V9a3 3 0 1 1 6 0v12', 'M18 3h.01', 'M6 3h.01'],
}
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    style="flex-shrink: 0"
  >
    <path v-for="(d, i) in (PATHS[name] || [])" :key="i" :d="d" />
  </svg>
</template>
