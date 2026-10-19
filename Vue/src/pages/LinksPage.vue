<script setup lang="ts">
import { reactive } from 'vue'
import { openUrl } from '@tauri-apps/plugin-opener'
import AppIcon from '../components/AppIcon.vue'

const sites = [
  { id: 'nist', name: 'NIST 谱线查询', domain: 'physics.nist.gov', icon: 'nist-spectrum', url: 'https://physics.nist.gov/PhysRefData/ASD/lines_form.html', description: '跃迁波长、跃迁几率与能级' },
  { id: 'finding', name: 'NIST 谱线速查', domain: 'physics.nist.gov', icon: 'spectrum-list', url: 'https://physics.nist.gov/PhysRefData/Handbook/Tables/findinglist.htm', description: '按波长区间查找元素谱线' },
  { id: 'asd', name: 'NIST ASD 总入口', domain: 'www.nist.gov', icon: 'atom-portal', url: 'https://www.nist.gov/pml/atomic-spectra-database', description: '原子光谱数据库官方入口' },
  { id: 'stark', name: 'STARK-B 展宽数据库', domain: 'stark-b.obspm.fr', icon: 'stark-plasma', url: 'https://stark-b.obspm.fr/', description: '谱线展宽与位移参数' },
  { id: 'scholar', name: 'Google 学术搜索', domain: 'scholar.google.com', icon: 'scholar-academic', url: 'https://scholar.google.com/', description: '论文与引用检索' }
] as const
type Site = typeof sites[number]
const pending = reactive<Record<Site['id'], boolean>>({ nist: false, finding: false, asd: false, stark: false, scholar: false })
const errors = reactive<Record<Site['id'], string>>({ nist: '', finding: '', asd: '', stark: '', scholar: '' })
async function openSite(site: Site) {
  if (pending[site.id]) return
  pending[site.id] = true
  errors[site.id] = ''
  try { await openUrl(site.url) }
  catch { errors[site.id] = '无法打开系统浏览器，请检查默认浏览器设置后重试。' }
  finally { pending[site.id] = false }
}
</script>

<template>
  <section class="links-page" aria-label="常用科研网站">
    <div class="links-grid">
      <article v-for="site in sites" :key="site.id" class="panel resource-card" :aria-labelledby="`resource-${site.id}`" :aria-busy="pending[site.id]">
        <div class="resource-top"><span class="resource-emblem"><AppIcon :name="site.icon" :size="24" /></span><h2 :id="`resource-${site.id}`">{{ site.name }}</h2></div>
        <p class="resource-description">{{ site.description }}</p>
        <div class="resource-footer"><span class="resource-domain" :title="site.url">{{ site.domain }}</span><button type="button" class="btn resource-open" :disabled="pending[site.id]" :aria-label="`在系统浏览器打开 ${site.name}`" :aria-describedby="errors[site.id] ? `resource-error-${site.id}` : undefined" @click="openSite(site)">{{ pending[site.id] ? '正在打开…' : errors[site.id] ? '重试访问' : '前往访问' }}<AppIcon name="arrow" :size="15" /></button></div>
        <p v-if="errors[site.id]" :id="`resource-error-${site.id}`" class="error-text resource-error" role="alert">{{ errors[site.id] }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.links-page{container-type:inline-size}
.links-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;align-items:stretch}
.resource-card{min-width:0;display:flex;flex-direction:column;padding:20px;border-radius:12px;transition:transform .18s,border-color .18s,box-shadow .18s}
.resource-card:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border));box-shadow:var(--shadow)}
.resource-card:focus-within{border-color:var(--accent)}
.resource-top{display:flex;align-items:center;gap:12px}
.resource-emblem{width:40px;height:40px;display:grid;place-items:center;flex:none;border:1px solid color-mix(in srgb,var(--accent) 22%,var(--border));border-radius:12px;color:var(--accent-text);background:color-mix(in srgb,var(--accent) 8%,var(--panel-soft))}
.resource-top h2{min-width:0;font-size:16px;line-height:1.5;margin:0;color:var(--text)}
.resource-description{flex:1;margin:14px 0 0;color:var(--muted);font-size:var(--text-body);line-height:1.7}
.resource-footer{margin-top:20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.resource-domain{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font:11px var(--font-code)}
.resource-open{flex:none;margin-left:auto;min-height:36px;gap:8px}
.resource-open .app-icon{transition:transform .18s}
.resource-open:hover:not(:disabled) .app-icon{transform:translateX(2px)}
.resource-open:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 55%,transparent);outline-offset:3px}
.resource-error{margin-bottom:0;font-size:var(--text-aux)}
@container(max-width:980px){.links-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@container(max-width:640px){.links-grid{grid-template-columns:minmax(0,1fr)}}
@media(prefers-reduced-motion:reduce){.resource-card,.resource-open .app-icon{transition:none}.resource-card:hover,.resource-open:hover:not(:disabled) .app-icon{transform:none}}
:global(:root[data-reduced-motion=true]) .resource-card,:global(:root[data-reduced-motion=true]) .resource-open .app-icon{transition:none}
:global(:root[data-reduced-motion=true]) .resource-card:hover,:global(:root[data-reduced-motion=true]) .resource-open:hover:not(:disabled) .app-icon{transform:none}
</style>
