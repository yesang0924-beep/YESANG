<script setup>
import Icon from './Icon.vue'

defineProps({
  autostart: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle-autostart', 'restart', 'stop', 'open-folder', 'export-diag'])
</script>

<template>
  <div class="hline">
    <label class="chk">
      <input
        type="checkbox"
        :checked="autostart"
        @change="emit('toggle-autostart', $event.target.checked)"
      >
      <span>开机自动启动守护</span>
    </label>
    <span class="spacer"></span>
    <button class="btn sm" @click="emit('restart')">
      <Icon name="refresh" :size="12" />重启网关
    </button>
    <button class="btn sm danger" @click="emit('stop')">
      <Icon name="power" :size="12" />停止全部
    </button>
    <button class="btn sm" @click="emit('open-folder')">
      <Icon name="folder" :size="12" />安装目录
    </button>
    <button class="btn sm" @click="emit('export-diag')">
      <Icon name="database" :size="12" />导出诊断包
    </button>
  </div>
</template>

<style scoped>
.hline { display: flex; gap: 9px; align-items: center; flex-wrap: wrap; }
.hline .spacer { flex: 1; }
.chk {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--fg-2);
  font-size: 12.5px;
}
.chk input { accent-color: var(--accent); cursor: pointer; }
</style>
