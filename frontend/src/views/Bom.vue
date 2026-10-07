<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const lines = ref<any[]>([])
const tree = ref<any[]>([])
const saving = ref(false)
const error = ref('')
const notice = ref('')
async function load() {
  lines.value = await api('/bom')
  tree.value = await api('/bom/tree')
}
async function save() {
  saving.value = true; error.value = ''; notice.value = ''
  try {
    const rates = lines.value.map(l => ({
      id: l.id,
      yield_rate: l.yield_rate === '' || l.yield_rate === null || l.yield_rate === undefined
        ? null : Number(l.yield_rate),
    }))
    const res = await api('/bom/yield-rates', { method: 'PUT', body: JSON.stringify({ rates }) })
    notice.value = `已保存：定义仓与当前备料单已按新出成率整张重写（${res.rewritten.length} 张当前单）`
    await load()
  } catch (e: any) {
    error.value = String(e?.message || e)
  } finally {
    saving.value = false
  }
}
onMounted(load)
</script>
<template>
  <h1>定额 · 出成率</h1>
  <p class="sub">出成率范围 (0, 1]，留空表示不折算（按 1 展开）· 保存后当前备料单整张重写，历史单不动</p>
  <div class="card">
    <table>
      <thead><tr><th>菜品</th><th>原料</th><th>定额 / 份</th><th>单位</th><th>出成率</th></tr></thead>
      <tbody>
        <tr v-for="l in lines" :key="l.id">
          <td>{{ l.dish_name }}</td>
          <td>{{ l.ingredient_name }}</td>
          <td>{{ l.qty_per_portion }}</td>
          <td>{{ l.unit }}</td>
          <td>
            <input
              v-model="l.yield_rate"
              type="number" min="0" max="1" step="0.01" placeholder="1"
              style="width:6rem;padding:0.2rem 0.35rem"
            />
          </td>
        </tr>
      </tbody>
    </table>
    <div style="margin-top:0.75rem;display:flex;align-items:center;gap:0.75rem">
      <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存出成率' }}</button>
      <span v-if="notice" class="badge badge-ok">{{ notice }}</span>
      <span v-if="error" class="badge badge-bad">{{ error }}</span>
    </div>
  </div>
  <div class="kp-bom-tree" style="max-width:420px">
    <h2>菜品 / BOM</h2>
    <div v-for="d in tree" :key="d.code" class="kp-dish-node">
      <strong>{{ d.dish }}</strong>
      <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
      <ul>
        <li v-for="(c,i) in d.children" :key="i">
          {{ c.ingredient }} · {{ c.qty }} {{ c.unit }} / 份
          <span v-if="c.yield_rate !== null && c.yield_rate !== undefined"> · 出成率 {{ c.yield_rate }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>
