<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId } from 'vue'
import AppIcon from './AppIcon.vue'
import { palettes, type Palette, type ThemeMode } from '../lib/preferences'
const props = defineProps<{ mode: ThemeMode; palette: Palette }>()
const emit = defineEmits<{ select: [mode: ThemeMode]; palette: [palette: Palette] }>()
const options: { mode: ThemeMode; label: string; icon: string }[] = [{ mode: 'light', label: '日间', icon: 'sun' }, { mode: 'dark', label: '夜间', icon: 'moon' }, { mode: 'system', label: '跟随系统', icon: 'monitor' }]
const selected = computed(() => options.find(option => option.mode === props.mode) ?? options[0]!)
type Menu = 'mode' | 'palette'
const opened = ref<Menu | null>(null), activeIndex = ref(0), root = ref<HTMLElement>()
const modeTrigger = ref<HTMLButtonElement>(), paletteTrigger = ref<HTMLButtonElement>()
const modeItems = ref<HTMLButtonElement[]>([]), paletteItems = ref<HTMLButtonElement[]>([])
const menuId = `theme-${useId()}`
const selectedPalette = computed(() => palettes.find(option => option.id === props.palette) ?? palettes[0]!)
function setItem(element: unknown, index: number, menu: Menu) { (menu === 'mode' ? modeItems : paletteItems).value[index] = element as HTMLButtonElement }
function focusItem(index: number) { (opened.value === 'mode' ? modeItems : paletteItems).value[index]?.focus() }
async function show(menu: Menu, index = menu === 'mode' ? options.findIndex(option => option.mode === props.mode) : palettes.findIndex(option => option.id === props.palette)) {
  activeIndex.value = Math.max(0, index); opened.value = menu; await nextTick(); focusItem(activeIndex.value)
}
async function close(restoreFocus = false) {
  const menu = opened.value; opened.value = null
  if (restoreFocus && menu) { await nextTick(); (menu === 'mode' ? modeTrigger : paletteTrigger).value?.focus() }
}
function toggle(menu: Menu) { if (opened.value === menu) void close(); else void show(menu) }
function choose(mode: ThemeMode) { emit('select', mode); void close(true) }
function choosePalette(palette: Palette) { emit('palette', palette); void close(true) }
function triggerKey(event: KeyboardEvent, menu: Menu) {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); void show(menu, event.key === 'ArrowUp' ? (menu === 'mode' ? options.length : palettes.length) - 1 : 0) }
  else if (event.key === 'Escape') { event.preventDefault(); void close(true) }
}
function menuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); void close(true); return }
  if (!opened.value) return
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); if (opened.value === 'mode') choose(options[activeIndex.value]!.mode); else choosePalette(palettes[activeIndex.value]!.id); return }
  const itemCount = opened.value === 'mode' ? options.length : palettes.length
  let next = activeIndex.value
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (next + 1) % itemCount
  else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (next + itemCount - 1) % itemCount
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = itemCount - 1
  else return
  event.preventDefault(); activeIndex.value = next; void nextTick(() => focusItem(next))
}
function outside(event: PointerEvent) { if (opened.value && !root.value?.contains(event.target as Node)) void close() }
function focusOut(event: FocusEvent) { if (!root.value?.contains(event.relatedTarget as Node | null)) void close() }
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => document.removeEventListener('pointerdown', outside))
</script>
<template>
  <div ref="root" class="theme-menu-control" @focusout="focusOut">
    <button ref="modeTrigger" type="button" class="icon-btn theme-trigger" :aria-label="`明暗模式：${selected.label}`" :title="`明暗模式：${selected.label}`" aria-haspopup="menu" :aria-expanded="opened === 'mode'" :aria-controls="menuId" @click="toggle('mode')" @keydown="triggerKey($event, 'mode')"><AppIcon :name="selected.icon" :size="18" /></button>
    <button ref="paletteTrigger" type="button" class="icon-btn theme-trigger" :aria-label="`主题配色：${selectedPalette.label}`" :title="`主题配色：${selectedPalette.label}`" aria-haspopup="menu" :aria-expanded="opened === 'palette'" :aria-controls="menuId" @click="toggle('palette')" @keydown="triggerKey($event, 'palette')"><AppIcon name="palette" :size="18" /></button>
    <Transition name="popover">
      <div v-if="opened" :id="menuId" :class="['theme-menu', { 'mode-menu': opened === 'mode' }]" role="menu" :aria-label="opened === 'mode' ? '明暗模式' : '主题配色'" @keydown="menuKey">
        <template v-if="opened === 'mode'">
          <button v-for="(option, index) in options" :key="option.mode" :ref="element => setItem(element, index, 'mode')" type="button" role="menuitemradio" :aria-checked="mode === option.mode" :tabindex="activeIndex === index ? 0 : -1" :class="{ selected: mode === option.mode }" @focus="activeIndex = index" @click="choose(option.mode)"><AppIcon :name="option.icon" :size="17" /><span>{{ option.label }}</span><AppIcon v-if="mode === option.mode" name="check" :size="15" class="theme-check" /></button>
        </template>
        <template v-else>
          <button v-for="(option, index) in palettes" :key="option.id" :ref="element => setItem(element, index, 'palette')" type="button" role="menuitemradio" :aria-checked="palette === option.id" :tabindex="activeIndex === index ? 0 : -1" :class="{ selected: palette === option.id }" @focus="activeIndex = index" @click="choosePalette(option.id)"><i class="palette-dot" :style="{ background: option.color }" /><span>{{ option.label }}</span><AppIcon v-if="palette === option.id" name="check" :size="15" class="theme-check" /></button>
        </template>
      </div>
    </Transition>
  </div>
</template>
