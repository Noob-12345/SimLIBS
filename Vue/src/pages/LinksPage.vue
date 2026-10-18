<script setup lang="ts">
import { reactive } from 'vue'
import { openUrl } from '@tauri-apps/plugin-opener'
import AppIcon from '../components/AppIcon.vue'

const sites = [
  { id: 'nist', name: 'NIST 原子光谱数据库', english: 'NIST ASD', domain: 'physics.nist.gov', icon: 'nist-spectrum', url: 'https://physics.nist.gov/PhysRefData/ASD/lines_form.html', description: '查询原子谱线、跃迁概率、能级及真空或空气波长。' },
  { id: 'stark', name: 'STARK-B 展宽数据库', english: 'STARK-B', domain: 'stark-b.obspm.fr', icon: 'stark-plasma', url: 'https://stark-b.obspm.fr/', description: '查询谱线展宽和位移参数，核对数据来源与温度、密度适用范围。' },
  { id: 'scholar', name: 'Google 学术搜索', english: 'Google Scholar', domain: 'scholar.google.com', icon: 'scholar-academic', url: 'https://scholar.google.com/', description: '检索 LIBS、等离子体诊断与光谱分析论文，查找文献及引用。' }
] as const
type Site = typeof sites[number]
const pending = reactive<Record<Site['id'], boolean>>({ nist: false, stark: false, scholar: false })
const errors = reactive<Record<Site['id'], string>>({ nist: '', stark: '', scholar: '' })
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
    <p class="links-intro">光谱数据与学术文献入口，在系统默认浏览器中打开。</p>
    <div class="links-grid">
      <article v-for="site in sites" :key="site.id" class="panel resource-card" :aria-labelledby="`resource-${site.id}`" :aria-busy="pending[site.id]">
        <div class="resource-top"><span class="resource-emblem"><AppIcon :name="site.icon" :size="27" /></span><span class="resource-english">{{ site.english }}</span><AppIcon name="external-link" class="resource-external" :size="16" /></div>
        <div class="resource-body"><h2 :id="`resource-${site.id}`">{{ site.name }}</h2><p>{{ site.description }}</p></div>
        <div class="resource-footer"><span class="resource-domain" :title="site.url">{{ site.domain }}</span><button type="button" class="btn resource-open" :disabled="pending[site.id]" :aria-label="`在系统浏览器打开 ${site.english}`" :aria-describedby="errors[site.id] ? `resource-error-${site.id}` : undefined" @click="openSite(site)">{{ pending[site.id] ? '正在打开…' : errors[site.id] ? '重试打开' : '前往访问' }}<AppIcon name="arrow" :size="15" /></button></div>
        <p v-if="errors[site.id]" :id="`resource-error-${site.id}`" class="error-text resource-error" role="alert">{{ errors[site.id] }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.links-intro{margin:0 0 24px;color:var(--muted);font-size:var(--text-body);line-height:1.7}
.links-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;align-items:stretch}
.resource-card{min-width:0;display:flex;flex-direction:column;padding:22px;border-radius:12px;transition:transform .18s,border-color .18s,box-shadow .18s}
.resource-card:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border));box-shadow:var(--shadow)}
.resource-card:focus-within{border-color:var(--accent)}
.resource-top{display:flex;align-items:center;gap:12px;margin-bottom:24px}
.resource-emblem{width:44px;height:44px;display:grid;place-items:center;flex:none;border:1px solid color-mix(in srgb,var(--accent) 22%,var(--border));border-radius:12px;color:var(--accent-text);background:color-mix(in srgb,var(--accent) 8%,var(--panel-soft))}
.resource-english{min-width:0;color:var(--muted);font-size:var(--text-meta);font-weight:600;letter-spacing:.04em}
.resource-external{margin-left:auto;flex:none;color:var(--faint)}
.resource-body{flex:1}
.resource-body h2{font-size:16px;line-height:1.5;margin:0 0 10px;color:var(--text)}
.resource-body p{margin:0;color:var(--muted);font-size:var(--text-body);line-height:1.8}
.resource-footer{margin-top:30px;display:flex;flex-direction:column;gap:14px;align-items:flex-start}
.resource-domain{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font:11px var(--font-code)}
.resource-open{width:100%;justify-content:space-between}
.resource-open:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 55%,transparent);outline-offset:3px}
.resource-error{margin-bottom:0;font-size:var(--text-aux)}
@media(max-width:1080px){.links-grid{grid-template-columns:1fr}.resource-top{margin-bottom:18px}.resource-footer{margin-top:22px}}
@media(prefers-reduced-motion:reduce){.resource-card:hover{transform:none}}
:global(:root[data-reduced-motion=true]) .resource-card:hover{transform:none}
</style>
