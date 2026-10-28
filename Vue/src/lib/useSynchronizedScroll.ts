import { nextTick, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'

export function useSynchronizedScroll(root: Ref<HTMLElement | undefined>, left: Ref<HTMLElement | undefined>, right: Ref<HTMLElement | undefined>, leftContent: Ref<HTMLElement | undefined>, rightContent: Ref<HTMLElement | undefined>, collapsed: Ref<boolean>) {
  const enabled = ref(false)
  let observer: ResizeObserver | undefined, frame = 0, media: MediaQueryList | undefined
  let leftTop = 0, rightTop = 0, disposed = false
  const fractions = new WeakMap<HTMLElement, { top: number; remainder: number }>()
  const clamp = (element: HTMLElement) => { element.scrollTop = Math.max(0, Math.min(element.scrollTop, element.scrollHeight - element.clientHeight)) }
  function measure() {
    frame = 0
    if (!root.value || !left.value || !right.value) return
    const wide = !!media?.matches
    if (wide !== enabled.value) {
      if (!wide) { leftTop = left.value.scrollTop; rightTop = right.value.scrollTop }
      else if (window.scrollY) window.scrollTo(0, 0)
      enabled.value = wide
      void nextTick(() => {
        if (disposed) return
        if (wide) { left.value!.scrollTop = leftTop; right.value!.scrollTop = rightTop }
        schedule()
      })
    }
    if (!wide) { root.value.style.removeProperty('--workbench-viewport-height'); return }
    const workspace = root.value.closest<HTMLElement>('.workspace')
    const bottom = workspace ? parseFloat(getComputedStyle(workspace).paddingBottom) || 0 : 16
    const height = Math.max(120, window.innerHeight - Math.max(8, root.value.getBoundingClientRect().top) - bottom)
    const value = height + 'px'
    if (root.value.style.getPropertyValue('--workbench-viewport-height') !== value) root.value.style.setProperty('--workbench-viewport-height', value)
    if (!collapsed.value) clamp(left.value)
    clamp(right.value)
  }
  function schedule() { if (!disposed && !frame) frame = requestAnimationFrame(measure) }
  function wheel(event: WheelEvent) {
    if (!enabled.value || event.defaultPrevented || !event.cancelable || event.ctrlKey || event.metaKey || event.shiftKey || !event.deltaY || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return
    const target = event.target instanceof Element ? event.target : null
    // Inner widgets retain native wheel behavior, even when already at their boundary.
    if (target?.closest('canvas,[role=menu],[role=listbox],[role=tooltip],.chart-tooltip,textarea,select,input[type=number],[data-independent-scroll]')) return
    const table = target?.closest<HTMLElement>('.table-scroll')
    if (table && table.scrollHeight > table.clientHeight + 1 && (event.deltaY > 0 ? table.scrollTop < table.scrollHeight - table.clientHeight : table.scrollTop > 0)) return
    if (!root.value || !left.value || !right.value) return
    const line = parseFloat(getComputedStyle(root.value).lineHeight) || 20
    const delta = event.deltaY * (event.deltaMode === WheelEvent.DOM_DELTA_LINE ? line : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? right.value.clientHeight : 1)
    event.preventDefault()
    for (const element of collapsed.value ? [right.value] : [left.value, right.value]) {
      const previous = fractions.get(element), top = element.scrollTop, max = Math.max(0, element.scrollHeight - element.clientHeight)
      const next = Math.max(0, Math.min(max, top + delta + (previous?.top === top ? previous.remainder : 0)))
      element.scrollTop = next
      fractions.set(element, { top: element.scrollTop, remainder: next > 0 && next < max ? next - element.scrollTop : 0 })
    }
  }
  watch(collapsed, () => { void nextTick(schedule) })
  onMounted(() => {
    media = window.matchMedia('(min-width: 741px)')
    media.addEventListener('change', schedule)
    root.value?.addEventListener('wheel', wheel, { passive: false })
    window.addEventListener('resize', schedule)
    window.addEventListener('scroll', schedule, true)
    observer = new ResizeObserver(schedule)
    for (const element of [root.value, leftContent.value, rightContent.value]) if (element) observer.observe(element)
    measure()
  })
  onUnmounted(() => {
    disposed = true
    root.value?.removeEventListener('wheel', wheel)
    media?.removeEventListener('change', schedule)
    window.removeEventListener('resize', schedule)
    window.removeEventListener('scroll', schedule, true)
    observer?.disconnect()
    if (frame) cancelAnimationFrame(frame)
  })
  return enabled
}
