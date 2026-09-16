<script setup>
defineProps({
  results: { type: Array, default: () => [] }, // [{ key,label,model,state,detail }]
})

const STATE_TEXT = { ok: '可用', warn: '限流中（稍后自动恢复）', fail: '不可用' }
</script>

<template>
  <div v-if="!results.length" class="empty">
    默认不做真实请求；点右上角「开始测试」后会调用模型，可能产生少量费用
  </div>
  <div v-else>
    <div v-for="r in results" :key="r.key" class="row">
      <span class="led" :class="r.state"></span>
      <span class="nm">{{ r.label }} <span class="sub">{{ r.model }}</span></span>
      <span class="tail">
        {{ STATE_TEXT[r.state] || r.state }}
        <template v-if="r.latency_ms != null"> · {{ r.latency_ms }}ms</template>
        <template v-if="r.detail"> · {{ String(r.detail).slice(0, 50) }}</template>
      </span>
    </div>
  </div>
</template>
