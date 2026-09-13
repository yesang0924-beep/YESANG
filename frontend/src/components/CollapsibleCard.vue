<script setup>
import { ref } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  title: { type: String, required: true },
  icon: { type: String, default: '' },
  tone: { type: String, default: 'blue' },   // 图标底座的配色
  badge: { type: [String, Number], default: null },
  note: { type: String, default: '' },
  defaultOpen: { type: Boolean, default: false },
})

const open = ref(props.defaultOpen)
</script>

<template>
  <section class="card" :class="{ open }">
    <div class="card-h" @click="open = !open">
      <span v-if="icon" class="icon-box sm" :class="tone">
        <Icon :name="icon" :size="14" />
      </span>
      <h2>{{ title }}</h2>
      <span v-if="badge !== null && badge !== ''" class="badge">{{ badge }}</span>
      <span class="spacer"></span>
      <span v-if="note" class="tag-note note">{{ note }}</span>
      <span class="actions" @click.stop><slot name="actions" /></span>
      <Icon class="arrow" name="chevron" :size="15" />
    </div>
    <div v-show="open" class="card-b"><slot /></div>
  </section>
</template>

<style scoped>
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: box-shadow .18s, border-color .18s, background .25s;
}
.card:hover { box-shadow: var(--shadow-hover); }

.card-h {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 14px 20px;
  cursor: pointer;
  user-select: none;
  transition: background .15s;
}
.card-h:hover { background: var(--card-2); }

.card-h h2 {
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: -.1px;
}

.badge {
  background: var(--card-3);
  color: var(--fg-2);
  border-radius: 20px;
  padding: 2px 10px;
  font-size: 11.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.spacer { flex: 1; }
.note { margin-right: 10px; }
.actions { display: flex; gap: 7px; }

.arrow {
  color: var(--fg-3);
  transition: transform .2s, color .2s;
  margin-left: 2px;
}
.card.open .arrow { transform: rotate(90deg); color: var(--accent); }

.card-b { padding: 0 20px 18px; }
</style>
