<script setup>
import Icon from './Icon.vue'

defineProps({
  // [{ value, label, icon, tone, status }]
  stats: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="stats">
    <div v-for="(s, i) in stats" :key="i" class="stat">
      <span class="icon-box sm" :class="s.tone || 'blue'">
        <Icon :name="s.icon || 'activity'" :size="14" />
      </span>
      <div class="body">
        <div class="v">{{ s.value }}</div>
        <div class="k">{{ s.label }}</div>
        <div v-if="s.status" class="st" :class="s.statusTone">{{ s.status }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--gap);
  padding: 0 28px 18px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  flex-shrink: 0;
}
.stat {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 16px 18px;
  box-shadow: var(--shadow-sm);
  display: flex;
  align-items: flex-start;
  gap: 12px;
  transition: box-shadow .18s, transform .18s, border-color .18s;
}
.stat:hover {
  box-shadow: var(--shadow-hover);
  transform: translateY(-2px);
}
.body { flex: 1; min-width: 0; }
.v {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -.5px;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}
.k { color: var(--fg-2); font-size: 12.5px; margin-top: 3px; }
.st {
  font-size: 11.5px;
  margin-top: 5px;
  font-weight: 500;
}
.st.ok   { color: var(--ok); }
.st.warn { color: var(--warn); }
.st.fail { color: var(--fail); }
</style>
