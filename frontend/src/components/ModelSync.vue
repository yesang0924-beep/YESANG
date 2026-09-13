<script setup>
import { ref, computed } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  upstreams: { type: Array, default: () => [] },
})
const emit = defineEmits(['fetch', 'import'])

const current = ref('')
const loading = ref(false)
const result = ref(null)          // { ok, total, models:[{id,slug,in_pool,known_chat_only}] }
const picked = ref({})            // { slug: true }
const filter = ref('')
const onlyNew = ref(true)

const visible = computed(() => {
  const list = (result.value && result.value.models) || []
  const kw = filter.value.trim().toLowerCase()
  return list.filter((m) => {
    if (onlyNew.value && m.in_pool) return false
    if (kw && !m.slug.toLowerCase().includes(kw)) return false
    return true
  })
})

const pickedList = computed(() =>
  Object.keys(picked.value).filter((k) => picked.value[k]))

const newCount = computed(() =>
  ((result.value && result.value.models) || []).filter((m) => !m.in_pool).length)

function pick(name) {
  current.value = name
  result.value = null
  picked.value = {}
  emit('fetch', name)
}

/** 父组件在拉取返回后调用 */
function setResult(r) {
  result.value = r
  loading.value = false
}
function setLoading(v) {
  loading.value = v
}
defineExpose({ setResult, setLoading })

function toggle(m) {
  if (m.in_pool) return
  picked.value = { ...picked.value, [m.slug]: !picked.value[m.slug] }
}
function selectAllNew() {
  const next = { ...picked.value }
  for (const m of (result.value && result.value.models) || []) {
    if (!m.in_pool) next[m.slug] = true
  }
  picked.value = next
}
function clearAll() {
  picked.value = {}
}
function doImport() {
  const ids = pickedList.value.map((s) => s.replace(/^[a-z]+\//, ''))
  if (!ids.length) return
  emit('import', { name: current.value, ids })
  picked.value = {}
}
function isPicked(slug) {
  return !!picked.value[slug]
}
</script>

<template>
  <div>
    <div class="picks">
      <button
        v-for="u in upstreams"
        :key="u.name"
        class="btn sm"
        :class="{ accent: current === u.name }"
        @click="pick(u.name)"
      >{{ u.label || u.name }}</button>
    </div>

    <div v-if="loading" class="empty">
      <span class="spin"></span> 正在从上游拉取模型列表…
    </div>

    <div v-else-if="result && !result.ok" class="err">
      <Icon name="alert" :size="14" /> {{ result.msg }}
    </div>

    <template v-else-if="result">
      <div class="hline">
        <span class="tag-note">
          共 {{ result.total }} 个 · 可导入 <b>{{ newCount }}</b> 个 · 已选 {{ pickedList.length }}
        </span>
        <span class="spacer"></span>
        <input v-model="filter" type="text" placeholder="搜索模型…" style="width: 170px">
        <label class="chk">
          <input v-model="onlyNew" type="checkbox"><span>只看未导入</span>
        </label>
        <button class="btn sm" @click="selectAllNew">全选可导入</button>
        <button class="btn sm ghost" @click="clearAll">清空</button>
        <button class="btn sm accent" :disabled="!pickedList.length" @click="doImport">
          <Icon name="plus" :size="12" />导入选中 {{ pickedList.length || '' }}
        </button>
      </div>

      <div class="grid">
        <div
          v-for="m in visible"
          :key="m.slug"
          class="chip"
          :class="{ owned: m.in_pool, on: isPicked(m.slug) }"
          @click="toggle(m)"
        >
          <Icon v-if="m.in_pool" name="check" :size="12" />
          <Icon v-else-if="isPicked(m.slug)" name="check" :size="12" />
          <span class="nm">{{ m.id }}</span>
          <span v-if="m.known_chat_only" class="tr" title="该模型需要协议翻译">译</span>
        </div>
        <div v-if="!visible.length" class="empty" style="grid-column: 1/-1">
          没有符合条件的模型
        </div>
      </div>
    </template>

    <div v-else class="empty">选一个上游，拉取它的模型列表</div>
  </div>
</template>

<style scoped>
.picks { display: flex; gap: 7px; flex-wrap: wrap; margin-bottom: 13px; }
.hline {
  display: flex; gap: 9px; align-items: center;
  margin-bottom: 12px; flex-wrap: wrap;
}
.hline .spacer { flex: 1; }
.chk {
  display: flex; align-items: center; gap: 6px;
  color: var(--fg-2); font-size: 12.5px; cursor: pointer;
}
.chk input { accent-color: var(--accent); cursor: pointer; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(178px, 1fr));
  gap: 7px;
  max-height: 300px;
  overflow-y: auto;
  padding-right: 4px;
}
.chip {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--card-2);
  font-size: 12px;
  cursor: pointer;
  transition: all .14s;
  min-width: 0;
}
.chip:hover { border-color: var(--accent); }
.chip .nm {
  flex: 1; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--fg);
}
.chip.on { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
.chip.owned {
  opacity: .5; cursor: default;
  border-style: dashed;
}
.chip.owned .nm { color: var(--fg-3); }
.tr {
  font-size: 9.5px; padding: 1px 5px; border-radius: 4px;
  background: var(--c-amber-bg); color: var(--c-amber);
  font-weight: 600; flex-shrink: 0;
}
.err {
  display: flex; align-items: center; gap: 7px;
  color: var(--fail); font-size: 12.5px; padding: 8px 0;
}
</style>
