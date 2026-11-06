<template>
  <!-- 实例列表：展示账号同步落库的云上 RDS 实例，可按账号 / 地域 / 关键字筛选 -->
  <div class="content-wrapper dmops-page">
    <div class="dmops-toolbar">
      <a-select
        v-model:value="filters.accountId"
        class="dmops-toolbar__account"
        :placeholder="$t('xuan-ze-zhang-hao')"
        :loading="accountsLoading"
        show-search
        option-filter-prop="label"
        @change="handleAccountChange"
      >
        <a-select-option v-for="item in accounts" :key="item.id" :value="item.id" :label="accountLabel(item)">
          {{ accountLabel(item) }}
        </a-select-option>
      </a-select>

      <a-select v-model:value="filters.region" class="dmops-toolbar__region" :loading="regionsLoading" @change="handleSearch">
        <a-select-option value="">{{ $t('quan-bu-di-qu') }}</a-select-option>
        <a-select-option v-for="region in regions" :key="region" :value="region">{{ region }}</a-select-option>
      </a-select>

      <a-input
        v-model:value="filters.keyword"
        class="dmops-toolbar__search"
        :placeholder="$t('sou-suo-shi-li')"
        allow-clear
        @press-enter="handleSearch"
      />
      <a-button :disabled="!filters.accountId" @click="handleSearch">{{ $t('cha-xun') }}</a-button>
      <div class="dmops-toolbar__right">
        <a-button :disabled="!filters.accountId" :loading="loading" @click="load">{{ $t('shua-xin') }}</a-button>
      </div>
    </div>

    <a-table
      class="dmops-table"
      :columns="columns"
      :data-source="items"
      :loading="loading"
      :pagination="false"
      :scroll="{ x: scrollX }"
      table-layout="fixed"
      row-key="id"
      size="middle"
    >
      <template #headerCell="{ column }">
        <div class="dmops-th">
          <span class="dmops-th__title">{{ column.title }}</span>
          <span class="dmops-th__resize" @mousedown.stop.prevent="startResize($event, column)" />
        </div>
      </template>
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'instance'">
          <div class="dmops-stack">
            <div class="dmops-stack__main dmops-name-line">
              <router-link v-if="record.instance_name" :to="instanceDetailRoute(record)" class="dmops-link" :title="record.instance_name">
                {{ record.instance_name }}
              </router-link>
              <span v-else class="dmops-muted">-</span>
              <a-tooltip v-if="record.instance_name" :title="$t('fu-zhi-shi-li-ming-cheng')">
                <button type="button" class="dmops-copy" @click.stop="copyInstanceName(record.instance_name)">
                  <CustomIcon type="icon-v2-CopyOutline" size="12px" />
                </button>
              </a-tooltip>
            </div>
            <span class="dmops-stack__sub">{{ record.instance_id }}</span>
          </div>
        </template>
        <template v-else-if="column.key === 'zone'">
          <div class="dmops-stack">
            <span v-if="record.zone_id" class="dmops-stack__main">{{ record.zone_id }}</span>
            <span v-else class="dmops-muted">-</span>
            <span v-if="record.region" class="dmops-stack__sub">{{ record.region }}</span>
          </div>
        </template>
        <template v-else-if="column.key === 'engine'">
          <span v-if="record.engine">{{ engineText(record) }}</span>
          <span v-else class="dmops-muted">-</span>
        </template>
        <template v-else-if="column.key === 'instance_type'">
          <span v-if="record.instance_type">{{ instanceTypeLabel(record.instance_type) }}</span>
          <span v-else class="dmops-muted">-</span>
        </template>
        <template v-else-if="column.key === 'instance_class'">
          <div class="dmops-stack">
            <span class="dmops-stack__main">{{ specText(record) }}</span>
            <span v-if="record.instance_class" class="dmops-stack__sub">{{ record.instance_class }}</span>
          </div>
        </template>
        <template v-else-if="column.key === 'disk'">
          <div v-if="hasDiskUsage(record)" class="dmops-stack">
            <div class="dmops-disk">
              <a-progress :percent="diskPercent(record)" :show-info="false" :stroke-color="diskColor(diskPercent(record))" size="small" />
              <span class="dmops-disk__percent" :style="{ color: diskColor(diskPercent(record)) }">{{ diskPercent(record) }}%</span>
            </div>
            <span class="dmops-stack__sub">{{ diskText(record) }}</span>
          </div>
          <span v-else class="dmops-muted">-</span>
        </template>
        <template v-else-if="column.key === 'status'">
          <a-tag v-if="record.status" :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          <span v-else class="dmops-muted">-</span>
        </template>
        <template v-else-if="column.key === 'endpoint'">
          <a-tooltip v-if="record.connection_string" :title="endpointText(record)" placement="topLeft">
            <span class="dmops-ellipsis">{{ endpointText(record) }}</span>
          </a-tooltip>
          <span v-else class="dmops-muted">-</span>
        </template>
        <template v-else-if="column.key === 'expire_time'">
          <span v-if="record.expire_time">{{ record.expire_time }}</span>
          <span v-else class="dmops-muted">-</span>
        </template>
      </template>
      <template #emptyText>
        <div class="dmops-empty">
          <span>{{ emptyText }}</span>
          <a-button v-if="!accounts.length && !accountsLoading" type="link" size="small" @click="goAccounts">
            {{ $t('zhang-hao-guan-li') }}
          </a-button>
        </div>
      </template>
    </a-table>

    <div v-if="total > 0" class="dmops-pagination">
      <Page
        :total="total"
        :page-size="pageSize"
        :model-value="page"
        show-total
        show-sizer
        @on-change="handlePageChange"
        @on-page-size-change="handlePageSizeChange"
      />
    </div>
  </div>
</template>

<script>
import copyMixin from '@/mixins/copyMixin';
import Toast from '@/utils/toast';
import { listAccountRegions, listAccounts, listInstances } from '@/services/http/dmops';
import { formatBytes, instanceTypeLabel, statusColor, statusLabel } from '@/views/dmops/utils/instance';

const PAGE_SIZE = 20;
const MIN_COLUMN_WIDTH = 80;
const COLUMN_WIDTHS = {
  instance: 224,
  zone: 126,
  owner: 120,
  level: 100,
  prodline: 120,
  engine: 140,
  instance_type: 120,
  instance_class: 176,
  disk: 230,
  status: 110,
  endpoint: 260,
  create_time: 170,
  expire_time: 170
};

export default {
  name: 'DmOpsInstanceList',
  mixins: [copyMixin],
  data() {
    return {
      accountsLoading: false,
      accounts: [],
      regionsLoading: false,
      regions: [],
      loading: false,
      items: [],
      total: 0,
      page: 1,
      pageSize: PAGE_SIZE,
      columnWidths: { ...COLUMN_WIDTHS },
      filters: {
        accountId: undefined,
        region: '',
        keyword: ''
      }
    };
  },
  computed: {
    columns() {
      return [
        { title: this.$t('shi-li-id-ming-cheng'), key: 'instance', width: this.columnWidths.instance },
        { title: this.$t('ke-yong-qu'), key: 'zone', width: this.columnWidths.zone },
        { title: this.$t('owner'), dataIndex: 'owner', key: 'owner', width: this.columnWidths.owner },
        { title: this.$t('level'), dataIndex: 'level', key: 'level', width: this.columnWidths.level },
        { title: this.$t('prodline'), dataIndex: 'prodline', key: 'prodline', width: this.columnWidths.prodline },
        { title: this.$t('shu-ju-ku-lei-xing'), key: 'engine', width: this.columnWidths.engine },
        { title: this.$t('shi-li-lei-xing'), key: 'instance_type', width: this.columnWidths.instance_type },
        { title: this.$t('shi-li-gui-ge'), key: 'instance_class', width: this.columnWidths.instance_class },
        { title: this.$t('ci-pan-shui-wei'), key: 'disk', width: this.columnWidths.disk },
        { title: this.$t('zhuang-tai'), key: 'status', width: this.columnWidths.status },
        { title: this.$t('lian-jie-di-zhi'), key: 'endpoint', width: this.columnWidths.endpoint },
        { title: this.$t('chuang-jian-shi-jian'), dataIndex: 'create_time', key: 'create_time', width: this.columnWidths.create_time },
        { title: this.$t('guo-qi-shi-jian'), key: 'expire_time', width: this.columnWidths.expire_time }
      ];
    },
    // 表格总宽跟随各列宽度之和，拖宽单列时整体宽度一起变化
    scrollX() {
      return this.columns.reduce((total, column) => total + (column.width || 0), 0);
    },
    emptyText() {
      if (this.accountsLoading) {
        return '';
      }
      if (!this.accounts.length) {
        return this.$t('qing-xian-zai-zhang-hao-guan-li-zhong-tian-jia-zhang-hao');
      }
      if (!this.filters.accountId) {
        return this.$t('qing-xian-xuan-ze-zhang-hao');
      }
      return this.$t('zan-wu-shi-li-shu-ju-qing-xian-tong-bu-shi-li');
    }
  },
  mounted() {
    this.loadAccounts();
  },
  methods: {
    startResize(event, column) {
      const startX = event.clientX;
      const startWidth = this.columnWidths[column.key];
      if (!startWidth) {
        return;
      }

      const handleMove = (moveEvent) => {
        const width = Math.max(MIN_COLUMN_WIDTH, startWidth + moveEvent.clientX - startX);
        this.columnWidths = { ...this.columnWidths, [column.key]: width };
      };
      const handleUp = () => {
        document.removeEventListener('mousemove', handleMove);
        document.removeEventListener('mouseup', handleUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };

      document.addEventListener('mousemove', handleMove);
      document.addEventListener('mouseup', handleUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    },
    accountLabel(account) {
      return account.cloud_account_id ? `${account.name}（${account.cloud_account_id}）` : account.name;
    },
    instanceDetailRoute(record) {
      return {
        name: 'DmOpsInstanceDetail',
        params: { instanceId: record.instance_id },
        query: { account_id: record.account_id, region: record.region }
      };
    },
    copyInstanceName(name) {
      this.copyText(name, this.$t('fu-zhi-cheng-gong'));
    },
    engineText(record) {
      return record.engine_version ? `${record.engine} ${record.engine_version}` : record.engine;
    },
    endpointText(record) {
      return record.port ? `${record.connection_string}:${record.port}` : record.connection_string;
    },
    memoryText(memoryMb) {
      return formatBytes(Number(memoryMb) * 1024 * 1024);
    },
    specText(record) {
      const parts = [];
      if (record.cpu) {
        parts.push(`${record.cpu} ${this.$t('he')}`);
      }
      if (record.memory_mb) {
        parts.push(this.memoryText(record.memory_mb));
      }
      return parts.length ? parts.join(' / ') : '-';
    },
    hasDiskUsage(record) {
      return record.disk_usage_percent !== null && record.disk_usage_percent !== undefined;
    },
    diskPercent(record) {
      return Math.max(0, Math.min(100, record.disk_usage_percent || 0));
    },
    diskText(record) {
      const capacityBytes = Number(record.storage_gb) * 1024 * 1024 * 1024;
      return `${formatBytes(record.disk_used_bytes)} / ${formatBytes(capacityBytes)}`;
    },
    diskColor(percent) {
      if (percent >= 85) {
        return '#f5222d';
      }
      if (percent >= 70) {
        return '#faad14';
      }
      return '#52c41a';
    },
    statusLabel(value) {
      return statusLabel(this.$t, value);
    },
    statusColor(value) {
      return statusColor(value);
    },
    instanceTypeLabel(value) {
      return instanceTypeLabel(this.$t, value);
    },
    async loadAccounts() {
      this.accountsLoading = true;
      try {
        const data = await listAccounts({ page: 1, page_size: 100 });
        this.accounts = data.items || [];
        const first = this.accounts.find((item) => item.enabled) || this.accounts[0];
        if (first) {
          this.filters.accountId = first.id;
          this.loadRegions(first.id);
          await this.load();
        }
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.accountsLoading = false;
      }
    },
    async loadRegions(accountId) {
      this.regionsLoading = true;
      this.regions = [];
      try {
        const data = await listAccountRegions(accountId);
        this.regions = data.regions || [];
      } catch (error) {
        // 地域只是筛选项，拉取失败不影响列表展示，保持「全部地域」即可。
        this.regions = [];
      } finally {
        this.regionsLoading = false;
      }
    },
    handleAccountChange(accountId) {
      this.filters.region = '';
      this.page = 1;
      this.items = [];
      this.total = 0;
      this.loadRegions(accountId);
      this.load();
    },
    async load() {
      if (!this.filters.accountId) {
        return;
      }
      this.loading = true;
      try {
        const params = {
          account_id: this.filters.accountId,
          page: this.page,
          page_size: this.pageSize
        };
        if (this.filters.region) {
          params.region = this.filters.region;
        }
        if (this.filters.keyword) {
          params.keyword = this.filters.keyword.trim();
        }

        const data = await listInstances(params);
        this.items = data.items || [];
        this.total = data.total || 0;
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.loading = false;
      }
    },
    handleSearch() {
      this.page = 1;
      this.load();
    },
    handlePageChange(page) {
      this.page = page;
      this.load();
    },
    handlePageSizeChange(_page, pageSize) {
      this.pageSize = pageSize;
      this.page = 1;
      this.load();
    },
    goAccounts() {
      this.$router.push('/dmops/accounts');
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-page {
  gap: 12px;
}

.dmops-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;

  &__account {
    width: 280px;
  }

  &__region {
    width: 160px;
  }

  &__search {
    width: 240px;
  }

  &__right {
    margin-left: auto;
  }
}

.dmops-table {
  :deep(.ant-table-cell) {
    vertical-align: middle;
  }

  // 让表头的拖拽手柄以单元格为定位基准
  :deep(.ant-table-thead > tr > th) {
    position: relative;
  }
}

.dmops-muted {
  color: var(--text-tertiary);
}

// 两行单元格：主信息在上，次要信息小一号灰色在下
.dmops-stack {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;

  &__main {
    overflow: hidden;
    color: var(--text-primary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__sub {
    overflow: hidden;
    font-size: 12px;
    color: var(--text-tertiary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

// 实例名称链接与复制按钮
.dmops-name-line {
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
}

.dmops-link {
  overflow: hidden;
  min-width: 0;
  color: var(--primary-color);
  text-overflow: ellipsis;
  white-space: nowrap;

  &:hover {
    // 全局 a:hover 会加 1px 底边框，这里只保留下划线，避免出现两条线
    border-bottom: none;
    text-decoration: underline;
  }
}

.dmops-copy {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  padding: 2px;
  color: var(--text-tertiary);
  background: transparent;
  border: none;
  cursor: pointer;

  &:hover {
    color: var(--primary-color);
  }
}

// 单行文本超长省略，配合 a-tooltip 展示完整内容
.dmops-ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dmops-disk {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;

  :deep(.ant-progress) {
    flex: 1;
    margin: 0;
    line-height: 1;
  }

  &__percent {
    flex-shrink: 0;
    font-weight: 500;
  }
}

// 表头拖拽调节列宽
.dmops-th {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 22px;

  &__title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__resize {
    position: absolute;
    top: -12px;
    right: -14px;
    bottom: -12px;
    width: 10px;
    cursor: col-resize;
    user-select: none;

    &::after {
      content: '';
      position: absolute;
      top: 50%;
      left: 50%;
      width: 1px;
      height: 14px;
      background: var(--border-light);
      opacity: 0;
      transform: translate(-50%, -50%);
      transition: opacity 0.12s ease;
    }

    &:hover::after {
      opacity: 1;
    }
  }
}

.dmops-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 24px 0;
  color: var(--text-tertiary);
}

.dmops-pagination {
  display: flex;
  justify-content: flex-end;
}
</style>
