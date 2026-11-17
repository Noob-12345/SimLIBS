<template>
  <div class="browser-sidebar-layout"><div class="browser-sidebar-controls"><div class="browser-sidebar-content"><slot name="controls" /></div></div><div class="browser-sidebar-results"><slot /></div></div>
</template>
<style scoped>
.browser-sidebar-layout{--browser-width:292px;display:grid;grid-template-columns:var(--browser-width) minmax(0,1fr);column-gap:40px;align-items:start;min-width:0}.browser-sidebar-controls{min-width:0}.browser-sidebar-content{width:var(--browser-width);display:flex;flex-direction:column;gap:16px}.browser-sidebar-results{min-width:0}@media(max-width:1100px){.browser-sidebar-layout{--browser-width:260px}}@media(max-width:740px){.browser-sidebar-layout{display:flex;flex-direction:column;gap:16px}.browser-sidebar-controls{order:2;width:100%}.browser-sidebar-content{width:100%}.browser-sidebar-results{order:1;width:100%}}
</style>
