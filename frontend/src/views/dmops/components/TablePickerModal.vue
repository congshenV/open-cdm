<template>
  <!--
    表数据校验弹窗：两级选表（库 → 表）。
    一级：库列表（单选，展示库下表数）；二级：表列表分页（每页 10，可搜索），
    点击行加入已选；已选区显示“库.表”Tag 可删。万级表场景下每层 DOM 恒定小。
  -->
  <a-modal :open="open" :title="$t('biao-shu-ju-jiao-yan')" :width="680" :mask-closable="false" @cancel="close">
    <a-spin :spinning="loading">
      <!-- 已选表（跨库） -->
      <div class="dmops-tpicker__selected">
        <span class="dmops-tpicker__label">{{ $t('yi-xuan') }}（{{ selected.length }}/{{ maxTables }}）</span>
        <a-tag v-for="item in selected" :key="item.key" class="dmops-tpicker__tag" closable @close="removeSelected(item)">
          {{ item.key }}
        </a-tag>
        <span v-if="!selected.length" class="dmops-field-hint">{{ $t('qing-xuan-ze-ku-he-biao') }}</span>
      </div>

      <div class="dmops-tpicker__cols">
        <!-- 一级：库列表 -->
        <div class="dmops-tpicker__dbcol">
          <div class="dmops-tpicker__title">{{ $t('ku') }}</div>
          <div class="dmops-tpicker__scroll">
            <div
              v-for="db in databases"
              :key="db.name"
              class="dmops-tpicker__row"
              :class="{ 'is-active': db.name === currentDb }"
              @click="switchDb(db.name)"
            >
              <span class="dmops-tpicker__name">{{ db.name }}</span>
              <span class="dmops-tpicker__count">{{ `${db.count} ${$t('zhang-biao')}` }}</span>
            </div>
            <div v-if="!databases.length" class="dmops-field-hint dmops-tpicker__more">-</div>
          </div>
        </div>

        <!-- 二级：当前库表列表（搜索 + 分页 10/页） -->
        <div class="dmops-tpicker__tablecol">
          <div class="dmops-tpicker__title">{{ currentDb ? `${currentDb} · ${$t('biao')}` : $t('biao') }}</div>
          <a-input-search
            v-if="currentDb"
            v-model:value="tableKeyword"
            :placeholder="$t('sou-suo-biao-zhan-wei')"
            allow-clear
            size="small"
            class="dmops-tpicker__search"
            @change="tablePage = 1"
          />
          <div class="dmops-tpicker__scroll">
            <template v-if="currentDb">
              <div
                v-for="item in pagedTables"
                :key="item.key"
                class="dmops-tpicker__row"
                :class="{ 'is-selected': isSelected(item), 'is-weak': !item.has_pk }"
                @click="toggle(item)"
              >
                <span class="dmops-tpicker__name">{{ item.table }}</span>
                <span class="dmops-tpicker__marks">
                  <a-tag v-if="!item.has_pk" color="red" class="dmops-tpicker__mark">{{ $t('wu-zhu-jian-jiang-tiao-guo') }}</a-tag>
                  <a-tag v-else-if="!item.has_auto_update" color="orange" class="dmops-tpicker__mark">
                    {{ $t('wu-geng-xin-lie-jiang-jiang-ji') }}
                  </a-tag>
                </span>
              </div>
              <div v-if="!filteredTables.length" class="dmops-field-hint dmops-tpicker__more">
                {{ tableKeyword ? $t('wu-pi-pei-jie-guo') : '-' }}
              </div>
            </template>
            <div v-else class="dmops-field-hint dmops-tpicker__more">{{ $t('qing-xian-xuan-ze-ku') }}</div>
          </div>
          <div v-if="filteredTables.length > pageSize" class="dmops-tpicker__pager">
            <Page
              :total="filteredTables.length"
              :page-size="pageSize"
              :model-value="tablePage"
              size="small"
              simple
              @on-change="(page) => (tablePage = page)"
            />
          </div>
        </div>
      </div>
    </a-spin>

    <template #footer>
      <a-button @click="close">{{ $t('qu-xiao') }}</a-button>
      <a-button type="primary" :loading="verifying" :disabled="!selected.length" @click="submit">
        {{ $t('kai-shi-jiao-yan') }}
      </a-button>
    </template>
  </a-modal>
</template>

<script>
import Toast from '@/utils/toast';
import { getDrillTables, verifyTableData } from '@/services/http/dmops';

// 表列表分页：每页 10 条（每层 DOM 恒定小，万级表不卡）。
const PAGE_SIZE = 10;

export default {
  name: 'DmOpsTablePickerModal',
  props: {
    open: {
      type: Boolean,
      default: false
    },
    drillId: {
      type: Number,
      default: 0
    }
  },
  emits: ['update:open', 'done'],
  data() {
    return {
      loading: false,
      verifying: false,
      tables: [],
      selected: [],
      currentDb: '',
      tableKeyword: '',
      tablePage: 1,
      pageSize: PAGE_SIZE,
      maxTables: 5
    };
  },
  computed: {
    // 库列表（聚合表数，按库名排序）。
    databases() {
      const byDb = new Map();
      this.tables.forEach((item) => {
        byDb.set(item.db, (byDb.get(item.db) || 0) + 1);
      });
      return [...byDb.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => a.name.localeCompare(b.name));
    },
    // 当前库的表（关键字过滤后）。
    filteredTables() {
      if (!this.currentDb) {
        return [];
      }
      const kw = this.tableKeyword.trim().toLowerCase();
      return this.tables.filter((item) => item.db === this.currentDb && (!kw || item.table.toLowerCase().includes(kw)));
    },
    pagedTables() {
      const start = (this.tablePage - 1) * this.pageSize;
      return this.filteredTables.slice(start, start + this.pageSize);
    }
  },
  watch: {
    open(value) {
      if (value) {
        this.reset();
        this.loadTables();
      }
    }
  },
  methods: {
    reset() {
      this.selected = [];
      this.tables = [];
      this.currentDb = '';
      this.tableKeyword = '';
      this.tablePage = 1;
    },
    close() {
      this.$emit('update:open', false);
    },
    // 库切换：回到第一页、清表搜索（保留已选——跨库累计）。
    switchDb(name) {
      this.currentDb = name;
      this.tableKeyword = '';
      this.tablePage = 1;
    },
    isSelected(item) {
      return this.selected.some((s) => s.key === item.key);
    },
    toggle(item) {
      if (this.isSelected(item)) {
        this.removeSelected(item);
        return;
      }
      if (this.selected.length >= this.maxTables) {
        Toast.warning(this.$t('zui-duo-xuan-ze-zhang-biao', { count: this.maxTables }));
        return;
      }
      this.selected.push(item);
    },
    removeSelected(item) {
      this.selected = this.selected.filter((s) => s.key !== item.key);
    },
    async loadTables() {
      if (!this.drillId) {
        return;
      }
      this.loading = true;
      try {
        const data = await getDrillTables(this.drillId);
        this.tables = (data.items || []).map((item) => ({
          ...item,
          key: `${item.db}.${item.table}`
        }));
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.loading = false;
      }
    },
    async submit() {
      if (!this.drillId || !this.selected.length || this.verifying) {
        return;
      }
      this.verifying = true;
      try {
        const data = await verifyTableData(
          this.drillId,
          this.selected.map((item) => item.key)
        );
        Toast.success(this.$t('biao-jiao-yan-wan-cheng', { passed: data.passed, total: data.total }));
        this.$emit('done', data);
        this.close();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.verifying = false;
      }
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-tpicker {
  &__selected {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: center;
    min-height: 32px;
    margin-bottom: 10px;
    padding: 8px;
    background: var(--bg-secondary);
    border-radius: 4px;
  }

  &__label {
    color: var(--text-secondary);
  }

  &__tag {
    font-family: Menlo, Monaco, 'Courier New', monospace;
  }

  &__cols {
    display: grid;
    grid-template-columns: 200px 1fr;
    gap: 12px;
  }

  &__title {
    margin-bottom: 6px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
  }

  &__scroll {
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-height: 300px;
    overflow-y: auto;
  }

  &__row {
    display: flex;
    gap: 8px;
    align-items: center;
    justify-content: space-between;
    padding: 4px 8px;
    font-size: 12px;
    cursor: pointer;
    border-radius: 2px;

    &:hover {
      background: var(--bg-secondary);
    }

    &.is-active {
      color: var(--primary-color);
      background: rgba(22, 119, 255, 0.06);
    }

    &.is-selected {
      color: var(--primary-color);
      background: rgba(22, 119, 255, 0.06);
    }

    &.is-weak {
      opacity: 0.75;
    }
  }

  &__name {
    overflow: hidden;
    font-family: Menlo, Monaco, 'Courier New', monospace;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__count {
    flex-shrink: 0;
    color: var(--text-tertiary);
  }

  &__marks {
    display: flex;
    flex-shrink: 0;
    gap: 4px;
  }

  &__mark {
    margin: 0;
    font-size: 11px;
    line-height: 16px;
  }

  &__search {
    margin-bottom: 6px;
  }

  &__pager {
    display: flex;
    justify-content: flex-end;
    padding-top: 4px;
  }

  &__more {
    padding: 8px;
    text-align: center;
  }
}
</style>
