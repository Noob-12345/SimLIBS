<script setup lang="ts">
import { reactive } from 'vue'
import { openUrl } from '@tauri-apps/plugin-opener'
import AppIcon from '../components/AppIcon.vue'

const sites = [
  { id: 'nist', name: 'NIST 原子光谱数据库', english: 'NIST ASD', category: '原子光谱基础库', features: ['跃迁几率 Aki', '激发能级 Ei/Ek', '真空 / 空气波长'], domain: 'physics.nist.gov', icon: 'nist-spectrum', url: 'https://physics.nist.gov/PhysRefData/ASD/lines_form.html', description: '查询原子谱线、跃迁概率、能级及真空或空气波长。' },
  { id: 'stark', name: 'STARK-B 展宽数据库', english: 'STARK-B', category: '碰撞展宽参数库', features: ['Stark 电子展宽', '位移参数', '适用温度密度'], domain: 'stark-b.obspm.fr', icon: 'stark-plasma', url: 'https://stark-b.obspm.fr/', description: '查询谱线展宽和位移参数，核对数据来源与温度、密度适用范围。' },
  { id: 'scholar', name: 'Google 学术搜索', english: 'Google Scholar', category: '科研文献与综述', features: ['LIBS 诊断文献', '定量定标模型', '引用追踪'], domain: 'scholar.google.com', icon: 'scholar-academic', url: 'https://scholar.google.com/', description: '检索 LIBS、等离子体诊断与光谱分析论文，查找文献及引用。' }
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
        <div class="resource-top"><span class="resource-emblem"><AppIcon :name="site.icon" :size="25" /></span><span class="resource-category">{{ site.category }}</span></div>
        <div class="resource-body"><span class="resource-english">{{ site.english }}</span><h2 :id="`resource-${site.id}`">{{ site.name }}</h2><p>{{ site.description }}</p><ul class="resource-features" :aria-label="`${site.english} 查询内容`"><li v-for="feature in site.features" :key="feature">{{ feature }}</li></ul></div>
        <div class="resource-footer"><span class="resource-domain" :title="site.url">{{ site.domain }}</span><button type="button" class="btn resource-open" :disabled="pending[site.id]" :aria-label="`在系统浏览器打开 ${site.english}`" :aria-describedby="errors[site.id] ? `resource-error-${site.id}` : undefined" @click="openSite(site)">{{ pending[site.id] ? '正在打开…' : errors[site.id] ? '重试打开' : '在系统浏览器打开' }}<AppIcon name="arrow" :size="15" /></button></div>
        <p v-if="errors[site.id]" :id="`resource-error-${site.id}`" class="error-text resource-error" role="alert">{{ errors[site.id] }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.links-intro{margin:0 0 24px;color:var(--muted);font-size:var(--text-body);line-height:1.7}
.links-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:18px;align-items:stretch}
.resource-card{min-width:0;display:flex;flex-direction:column;padding:22px;border-radius:12px;transition:transform .18s,border-color .18s,box-shadow .18s}
.resource-card:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--border));box-shadow:var(--shadow)}
.resource-card:focus-within{border-color:var(--accent)}
.resource-top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:24px}
.resource-emblem{width:42px;height:42px;display:grid;place-items:center;flex:none;border:1px solid color-mix(in srgb,var(--accent) 22%,var(--border));border-radius:12px;color:var(--accent-text);background:color-mix(in srgb,var(--accent) 8%,var(--panel-soft))}
.resource-category{color:var(--muted);font-size:11px;line-height:1.6;text-align:right}
.resource-english{display:block;margin-bottom:6px;min-width:0;color:var(--accent-text);font-size:var(--text-meta);font-weight:600;letter-spacing:.04em}
.resource-body{flex:1}
.resource-body h2{font-size:16px;line-height:1.5;margin:0 0 10px;color:var(--text)}
.resource-body p{margin:0;color:var(--muted);font-size:var(--text-body);line-height:1.8}
.resource-features{display:flex;flex-wrap:wrap;gap:6px;margin:18px 0 0;padding:0;list-style:none}
.resource-features li{padding:3px 7px;border-radius:5px;background:var(--accent-soft);color:var(--accent-text);font-size:11px;line-height:1.5}
.resource-footer{margin-top:30px;display:flex;flex-direction:column;gap:14px;align-items:flex-start}
.resource-domain{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font:11px var(--font-code)}
.resource-open{width:100%;min-height:40px;justify-content:space-between}
.resource-open .app-icon{transition:transform .18s}
.resource-open:hover:not(:disabled) .app-icon{transform:translateX(2px)}
.resource-open:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 55%,transparent);outline-offset:3px}
.resource-error{margin-bottom:0;font-size:var(--text-aux)}
@media(prefers-reduced-motion:reduce){.resource-card,.resource-open .app-icon{transition:none}.resource-card:hover,.resource-open:hover:not(:disabled) .app-icon{transform:none}}
:global(:root[data-reduced-motion=true]) .resource-card,:global(:root[data-reduced-motion=true]) .resource-open .app-icon{transition:none}
:global(:root[data-reduced-motion=true]) .resource-card:hover,:global(:root[data-reduced-motion=true]) .resource-open:hover:not(:disabled) .app-icon{transform:none}
</style>
