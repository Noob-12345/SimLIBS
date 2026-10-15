<script setup lang="ts">
defineProps<{ format: 'csv' | 'json' | 'png' }>()
</script>
<template>
  <svg class="file-format-icon" viewBox="0 0 40 44" width="40" height="44" fill="none" stroke-linecap="round" aria-hidden="true">
    <path d="M8 2h17l12 12v24a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4V6a4 4 0 0 1 4-4Z" fill="currentColor" fill-opacity=".07" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
    <path d="M25 2v12h12" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
    <text x="20" y="30" fill="currentColor" text-anchor="middle" font-size="11" font-weight="700">{{ format.toUpperCase() }}</text>
  </svg>
</template>
