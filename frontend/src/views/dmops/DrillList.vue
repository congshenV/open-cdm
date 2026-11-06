<template>
  <!-- 演练历史列表：按账号/实例/状态过滤，含"未下线"过滤与确认下线入口 -->
  <div class="content-wrapper dmops-drill-list">
    <div class="dmops-drill-toolbar">
      <span class="dmops-drill-toolbar__label">{{ $t('zhang-hao') }}</span>
      <a-select v-model:value="filterAccountId" allow-clear style="width: 180px" :placeholder="$t('quan-bu')" @change="handleFilterChange">
        <a-select-option v-for="account in accounts" :key="account.id" :value="account.id">
          {{ account.name }}（{{ account.cloud_account_id }}）
        </a-select-option>
      </a-select>
      <a-input
        v-model:value="filterInstanceId"
        style="width: 220px"
        allow-clear
        :placeholder="$t('shi-li-id-zhan-wei')"
        @press-enter="handleFilterChange"
      />
      <a-select v-model:value="filterStatus" allow-clear style="width: 130px" :placeholder="$t('zhuang-tai')" @change="handleFilterChange">
        <a-select-option v-for="status in statusOptions" :key="status" :value="status">
          {{ drillStatusLabel(status) }}
        </a-select-option>
      </a-select>
      <a-checkbox v-model:checked="filterOffline" @change="handleFilterChange">
        {{ $t('jin-kai-dai-xia-xian') }}
      </a-checkbox>
      <a-button :loading="loading" @click="loadDrills">{{ $t('cha-xun') }}</a-button>
    </div>

    <a-table :columns="columns" :data-source="items" :loading="loading" :pagination="false" row-key="id" size="small">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'drill_no'">
          <a class="dmops-drill-link" @click="openDetail(record)">{{ record.drill_no }}</a>
        </template>
        <template v-else-if="column.key === 'status'">
          <a-tag :color="drillStatusColor(record.display_status)">{{ drillStatusLabel(record.display_status) }}</a-tag>
        </template>
        <template v-else-if="column.key === 'backup'">
          {{ text(record.backup_id) }}
        </template>
        <template v-else-if="column.key === 'clone_instance_id'">
          <span v-if="record.clone_instance_id" class="dmops-drill-mono">{{ record.clone_instance_id }}</span>
          <span v-else class="dmops-muted">-</span>
        </template>
        <template v-else-if="column.key === 'offline'">
          <template v-if="record.clone_instance_id">
            <a-tag v-if="record.offline_status === 1" color="green">{{ $t('yi-que-ren-xia-xian') }}</a-tag>
            <a-tag v-else color="orange">{{ $t('dai-xia-xian') }}</a-tag>
          </template>
          <span v-else class="dmops-muted">-</span>
        </template>
        <template v-else-if="column.key === 'actions'">
          <a v-if="record.clone_instance_id && record.offline_status === 0" class="dmops-drill-link" @click="openConfirmOffline(record)">
            {{ $t('que-ren-xia-xian') }}
          </a>
          <span v-else class="dmops-muted">-</span>
        </template>
      </template>
    </a-table>

    <div v-if="total > 0" class="dmops-pagination">
      <Page :total="total" :page-size="pageSize" :model-value="page" show-total @on-change="handlePageChange" />
    </div>

    <a-modal v-model:open="confirmOpen" :title="$t('que-ren-xia-xian')" :mask-closable="false" @cancel="confirmOpen = false">
      <p class="dmops-drill-confirm-text">{{ $t('que-ren-xia-xian-ti-shi') }}</p>
      <p v-if="confirmTarget" class="dmops-drill-confirm-meta">
        {{ `${confirmTarget.drill_no} · ${confirmTarget.clone_instance_id}` }}
      </p>
      <template #footer>
        <a-button @click="confirmOpen = false">{{ $t('qu-xiao') }}</a-button>
        <a-button type="primary" :loading="confirming" @click="handleConfirmOffline">
          {{ $t('que-ren') }}
        </a-button>
      </template>
    </a-modal>
  </div>
</template>

<script>
import Toast from '@/utils/toast';
import { confirmDrillOffline, listAccounts, listBackupDrills } from '@/services/http/dmops';
import { drillLabels } from '@/views/dmops/utils/drill';

// 一期状态选项（comparing/partial 二期接口出现后自动可选）。
const STATUS_OPTIONS = ['pending', 'cloning', 'success', 'failed', 'canceled'];

export default {
  name: 'DmOpsDrillList',
  mixins: [drillLabels],
  data() {
    return {
      accounts: [],
      filterAccountId: undefined,
      filterInstanceId: '',
      filterStatus: undefined,
      filterOffline: false,
      loading: false,
      items: [],
      total: 0,
      page: 1,
      pageSize: 20,
      statusOptions: STATUS_OPTIONS,
      confirmOpen: false,
      confirmTarget: null,
      confirming: false
    };
  },
  computed: {
    columns() {
      return [
        { title: this.$t('yan-lian-bian-hao'), key: 'drill_no', width: 130 },
        { title: this.$t('yuan-shi-li'), dataIndex: 'source_instance_id', key: 'source_instance_id', width: 120 },
        { title: this.$t('di-qu'), dataIndex: 'region', key: 'region', width: 100 },
        { title: this.$t('bei-fen-id'), dataIndex: 'backup_id', key: 'backup_id', width: 110 },
        { title: this.$t('zhuang-tai'), key: 'status', width: 90 },
        { title: this.$t('ke-long-shi-li'), key: 'clone_instance_id', width: 120 },
        { title: this.$t('fa-qi-shi-jian'), dataIndex: 'created_at', key: 'created_at', width: 150 },
        { title: this.$t('xia-xian-zhuang-tai'), key: 'offline', width: 110 },
        { title: this.$t('cao-zuo'), key: 'actions', width: 100 }
      ];
    }
  },
  mounted() {
    this.loadAccounts();
    this.loadDrills();
  },
  methods: {
    text(value) {
      return value === null || value === undefined || value === '' ? '-' : String(value);
    },
    async loadAccounts() {
      try {
        const data = await listAccounts({ enabled: true });
        this.accounts = (data && data.items) || [];
      } catch (error) {
        // 账号下拉加载失败不阻塞列表本身
        this.accounts = [];
      }
    },
    handleFilterChange() {
      this.page = 1;
      this.loadDrills();
    },
    handlePageChange(page) {
      this.page = page;
      this.loadDrills();
    },
    async loadDrills() {
      this.loading = true;
      try {
        const params = {
          page: this.page,
          page_size: this.pageSize
        };
        if (this.filterAccountId) {
          params.account_id = this.filterAccountId;
        }
        const instanceId = String(this.filterInstanceId || '').trim();
        if (instanceId) {
          params.instance_id = instanceId;
        }
        if (this.filterStatus) {
          params.status = this.filterStatus;
        }
        if (this.filterOffline) {
          params.offline = 1;
        }
        const data = await listBackupDrills(params);
        this.items = data.items || [];
        this.total = data.total || 0;
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.loading = false;
      }
    },
    openDetail(record) {
      this.$router.push(`/dmops/drill/${record.id}`).catch(() => {});
    },
    openConfirmOffline(record) {
      this.confirmTarget = record;
      this.confirmOpen = true;
    },
    async handleConfirmOffline() {
      if (!this.confirmTarget || this.confirming) {
        return;
      }
      this.confirming = true;
      try {
        await confirmDrillOffline(this.confirmTarget.id);
        Toast.success(this.$t('cao-zuo-cheng-gong'));
        this.confirmOpen = false;
        await this.loadDrills();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.confirming = false;
      }
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-drill-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dmops-drill-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;

  &__label {
    color: var(--text-secondary);
  }
}

.dmops-drill-link {
  color: var(--primary-color);
  cursor: pointer;
}

.dmops-drill-mono {
  font-family: Menlo, Monaco, 'Courier New', monospace;
  word-break: break-all;
}

.dmops-drill-confirm-text {
  margin-bottom: 8px;
}

.dmops-drill-confirm-meta {
  margin-bottom: 0;
  font-size: 13px;
  color: var(--text-tertiary);
  word-break: break-all;
}

.dmops-muted {
  color: var(--text-tertiary);
}

.dmops-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
