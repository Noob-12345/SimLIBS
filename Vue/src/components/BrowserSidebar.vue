<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { spectrumBrowser as state } from '../lib/spectrumBrowser'
const id=useId(),root=ref<HTMLElement>(),controls=ref<HTMLElement>(),toggle=ref<HTMLButtonElement>()
const position=ref({left:0,top:0,visible:false})
let observer:ResizeObserver|undefined,frame=0
function measure(){frame=0;if(!root.value)return;const box=root.value.getBoundingClientRect(),side=controls.value?.getBoundingClientRect(),narrow=innerWidth<=740;const top=Math.max(80,box.top),bottom=Math.min(innerHeight-24,box.bottom);position.value={left:state.sidebarCollapsed?box.left+2:narrow?Math.min(innerWidth-28,box.right-12):(side?.right??box.left)+9,top:Math.max(90,(top+bottom)/2-48),visible:box.top<innerHeight&&box.bottom>75}}
function schedule(){if(!frame)frame=requestAnimationFrame(measure)}
async function flip(){const collapsed=!state.sidebarCollapsed;if(collapsed&&controls.value?.contains(document.activeElement))toggle.value?.focus({preventScroll:true});state.sidebarCollapsed=collapsed;await nextTick();schedule();toggle.value?.focus({preventScroll:true})}
watch(()=>state.sidebarCollapsed,()=>void nextTick(schedule))
onMounted(()=>{observer=new ResizeObserver(schedule);observer.observe(root.value!);if(controls.value)observer.observe(controls.value);window.addEventListener('resize',schedule);window.addEventListener('scroll',schedule,true);schedule()})
onUnmounted(()=>{observer?.disconnect();window.removeEventListener('resize',schedule);window.removeEventListener('scroll',schedule,true);cancelAnimationFrame(frame)})
</script>
<template>
  <div ref="root" :class="['browser-sidebar-layout',{'is-collapsed':state.sidebarCollapsed}]"><div ref="controls" :class="['browser-sidebar-controls',{'is-collapsed':state.sidebarCollapsed}]"><div :id="id" class="browser-sidebar-content" :inert="state.sidebarCollapsed" :aria-hidden="state.sidebarCollapsed"><slot name="controls" /></div></div><div class="browser-sidebar-results"><slot /></div><Teleport to="body"><button v-show="position.visible" ref="toggle" type="button" class="workbench-edge edge-active browser-sidebar-toggle" :aria-controls="id" :aria-expanded="!state.sidebarCollapsed" :aria-label="state.sidebarCollapsed?'展开光谱浏览设置':'收起光谱浏览设置'" :title="state.sidebarCollapsed?'展开设置':'收起设置'" :style="{left:position.left+'px',top:position.top+'px'}" @click="flip"><AppIcon name="chevron" :size="18" /></button></Teleport></div>
</template>
<style scoped>
.browser-sidebar-layout{--browser-width:292px;display:grid;grid-template-columns:var(--browser-width) minmax(0,1fr);column-gap:40px;align-items:start;min-width:0;transition:grid-template-columns .3s ease,column-gap .3s ease}.browser-sidebar-layout.is-collapsed{grid-template-columns:0px minmax(0,1fr);column-gap:0}.browser-sidebar-controls{min-width:0}.browser-sidebar-controls.is-collapsed{overflow:hidden;width:0}.browser-sidebar-content{width:var(--browser-width);display:flex;flex-direction:column;gap:16px}.browser-sidebar-results{min-width:0}.browser-sidebar-toggle{height:96px}.browser-sidebar-toggle:focus-visible{outline:2px solid var(--accent-text);outline-offset:4px}@media(max-width:1100px){.browser-sidebar-layout{--browser-width:260px}}@media(max-width:740px){.browser-sidebar-layout{display:flex;flex-direction:column;gap:16px}.browser-sidebar-controls{order:2;width:100%}.browser-sidebar-content{width:100%}.browser-sidebar-results{order:1;width:100%}.browser-sidebar-controls.is-collapsed{height:0;visibility:hidden}.browser-sidebar-toggle{right:9px;left:auto!important}}@media(prefers-reduced-motion:reduce){.browser-sidebar-layout{transition:none}}:global(:root[data-reduced-motion=true]) .browser-sidebar-layout{transition:none}
</style>
