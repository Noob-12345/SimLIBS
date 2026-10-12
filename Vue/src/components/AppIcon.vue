<script setup lang="ts">
defineProps<{ name: string; size?: number }>()
const paths: Record<string, string> = {
  single: 'M9 3h6M10 3v6L4 18a2 2 0 0 0 1.7 3h12.6a2 2 0 0 0 1.7-3l-6-9V3M7.5 15h9',
  batch: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  scan: 'M2 12h4l3-8 4 16 3-8h6',
  jobs: 'M21 12a9 9 0 1 1-9-9 9 9 0 0 1 9 9M12 7v5l3 2',
  settings: 'M4 6h16M4 12h16M4 18h16M9 3v6M15 9v6M8 15v6',
  plus: 'M12 5v14M5 12h14', minus: 'M5 12h14', close: 'M6 6l12 12M18 6 6 18',
  reset: 'M3 10a9 9 0 1 1 2 8M3 4v6h6', chevron: 'm9 5 7 7-7 7', down: 'm5 9 7 7 7-7',
  play: 'm8 5 11 7-11 7z', pause: 'M8 5v14M16 5v14', prev: 'M5 5v14m14-14L8 12l11 7z', next: 'M19 5v14M5 5l11 7-11 7z',
  download: 'M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6', refresh: 'M20 7a9 9 0 0 0-15-1L3 9m0-5v5h5M4 17a9 9 0 0 0 15 1l2-3m0 5v-5h-5',
  sun: 'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5',
  moon: 'M20 14.5A8 8 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5', monitor: 'M3 4h18v13H3zM8 21h8M12 17v4',
  check: 'm5 12 4 4L19 6', arrow: 'M5 12h14m-6-6 6 6-6 6', file: 'M14 2H5v20h14V7l-5-5v5h5M8 12h8M8 16h6',
  save: 'M4 3h13l4 4v14H3V3h1M7 3v6h10V3M7 21v-8h10v8', info: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M12 11v6M12 7v.2',
  folder: 'M3 7V4h6l2 3h10v13H3V7z', palette: 'M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 0-4h-1a2 2 0 0 1 0-4h5a4 4 0 0 0 4-4c0-3-4-6-9-6M7 8h.1M11 6h.1M16 7h.1M6 13h.1',
  github: 'M9 19c-4.3 1.3-4.3-2.5-6-3m12 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 19 4.77 5.07 5.07 0 0 0 18.91 1S17.73.65 15 2.48a13.38 13.38 0 0 0-7 0C5.27.65 4.09 1 4.09 1A5.07 5.07 0 0 0 4 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 8 18.13V22'
}
</script>
<template><svg :width="size || 18" :height="size || 18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="app-icon"><path :d="paths[name] || paths.info" /></svg></template>
