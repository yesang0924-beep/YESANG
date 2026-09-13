<script setup>
import { ref, reactive } from 'vue'

const props = defineProps({
  configs: { type: Array, default: () => [] },
})
const emit = defineEmits(['save', 'test'])

const editing = ref('')
const draft = reactive({ base: '', key: '', use_proxy: true })
const testing = ref('')
const results = reactive({})

function toggle(u) {
  if (editing.value === u.name) {
    editing.value = ''
    return
  }
  editing.value = u.name
  draft.base = u.base
  draft.key = ''
  draft.use_proxy = u.use_proxy
  delete results[u.name]
}

function cancel() {
  editing.value = ''
}

function submit(u) {
  emit('save', {
    name: u.name,
    base: draft.base,
    use_proxy: draft.use_proxy,
    key: draft.key,
  })
  editing.value = ''
}

async function runTest(u) {
  testing.value = u.name
  results[u.name] = null
  emit('test', {
    name: u.name,
    base: draft.base,
    key: draft.key,
    use_proxy: draft.use_proxy,
  })
}

/** 由父组件在测试返回后调用 */
function setResult(name, r) {
  results[name] = r
  testing.value = ''
}

defineExpose({ setResult })
</script>

<template>
  <div v-if="!configs.length" class="empty">上游配置读取中…</div>

  <div v-for="u in configs" :key="u.name" class="block">
    <div class="row">
      <span class="led" :class="u.has_key ? 'ok' : 'fail'"></span>
      <span class="nm">
        {{ u.label }}
        <span class="sub">{{ u.base }}</span>
      </span>
      <span class="tail">{{ u.routes.join(' ') || '—' }}</span>
      <span class="tail">{{ u.key_masked || '无密钥' }}</span>
      <span class="tail">{{ u.use_proxy ? '经线路' : '直连' }}</span>
      <button class="btn sm" @click="toggle(u)">{{ editing === u.name ? '收起' : '编辑' }}</button>
    </div>

    <div v-if="editing === u.name" class="editor">
      <label class="fld">
        <span>接口地址</span>
        <input v-model="draft.base" type="text" :placeholder="u.base">
      </label>

      <label class="fld">
        <span>密钥</span>
        <input
          v-model="draft.key"
          type="text"
          :placeholder="u.has_key ? '留空则保持不变（当前 ' + u.key_masked + '）' : '尚未配置，请填入'"
        >
      </label>

      <label class="chk">
        <input v-model="draft.use_proxy" type="checkbox">
        <span>经出口线路访问（境外上游建议开启）</span>
      </label>

      <div class="acts">
        <button class="btn accent sm" @click="submit(u)">保存</button>
        <button class="btn sm" :disabled="testing === u.name" @click="runTest(u)">
          <span v-if="testing === u.name" class="spin"></span>
          {{ testing === u.name ? ' 测试中' : '连通性测试' }}
        </button>
        <button class="btn ghost sm" @click="cancel">取消</button>
        <span class="spacer"></span>
        <span class="tag-note">改地址后需重启网关生效</span>
      </div>

      <div v-if="results[u.name]" class="result" :class="results[u.name].ok ? 'good' : 'bad'">
        {{ results[u.name].ok ? '✓ ' : '✕ ' }}{{ results[u.name].text }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.block { border-bottom: 1px solid var(--border); }
.block:last-child { border-bottom: none; }
.block .row { border-bottom: none; }

.editor {
  background: var(--card-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 13px 15px;
  margin: 4px 0 12px;
  display: flex; flex-direction: column; gap: 10px;
}
.fld { display: flex; flex-direction: column; gap: 5px; }
.fld > span { color: var(--fg-3); font-size: 11.5px; }
.fld input { width: 100%; }
.chk {
  display: flex; align-items: center; gap: 8px;
  color: var(--fg-2); font-size: 12.5px; cursor: pointer;
}
.chk input { accent-color: var(--accent); cursor: pointer; }
.acts { display: flex; gap: 8px; align-items: center; margin-top: 2px; }
.acts .spacer { flex: 1; }
.result { font-size: 12px; padding: 7px 11px; border-radius: 8px; word-break: break-all; }
.result.good { background: rgba(34, 197, 94, .1); color: var(--ok); }
.result.bad  { background: rgba(239, 68, 68, .1); color: var(--fail); }
</style>
