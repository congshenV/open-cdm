<template>
  <div class="content-wrapper dmops-page">
    <div class="dmops-toolbar">
      <a-input
        v-model:value="filters.keyword"
        class="dmops-toolbar__search"
        :placeholder="$t('sou-suo-zhang-hao')"
        allow-clear
        @press-enter="handleSearch"
      />
      <a-select v-model:value="filters.enabled" class="dmops-toolbar__status" @change="handleSearch">
        <a-select-option value="">{{ $t('quan-bu-zhuang-tai') }}</a-select-option>
        <a-select-option value="true">{{ $t('qi-yong') }}</a-select-option>
        <a-select-option value="false">{{ $t('ting-yong') }}</a-select-option>
      </a-select>
      <a-button @click="handleSearch">{{ $t('cha-xun') }}</a-button>
      <div class="dmops-toolbar__right">
        <a-button type="primary" @click="openCreate">{{ $t('xin-jian-zhang-hao') }}</a-button>
      </div>
    </div>

    <a-table class="dmops-table" :columns="columns" :data-source="items" :loading="loading" :pagination="false" row-key="id" size="middle">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'enabled'">
          <a-tag :color="record.enabled ? 'green' : 'default'">
            {{ record.enabled ? $t('yi-qi-yong') : $t('wei-qi-yong') }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'credential'">
          <span v-if="record.credential_configured">{{ typeLabel(record.credential_type) }}</span>
          <span v-else class="dmops-muted">{{ $t('wei-pei-zhi') }}</span>
        </template>
        <template v-else-if="column.key === 'last_sync'">
          <div v-if="record.last_sync_at" class="dmops-sync">
            <span>{{ record.last_sync_at }}</span>
            <a-tag :color="syncStatusColor(record.last_sync_status)">{{ syncStatusLabel(record.last_sync_status) }}</a-tag>
          </div>
          <span v-else class="dmops-muted">-</span>
        </template>
        <template v-else-if="column.key === 'actions'">
          <div class="dmops-actions">
            <a-button type="link" size="small" @click="openCredential(record)">{{ $t('she-zhi-ping-zheng') }}</a-button>
            <a-button
              type="link"
              size="small"
              :disabled="!record.credential_configured || !record.enabled"
              :loading="syncingId === record.id"
              @click="handleSync(record)"
            >
              {{ $t('tong-bu-shi-li') }}
            </a-button>
            <a-button type="link" size="small" @click="openEdit(record)">{{ $t('bian-ji') }}</a-button>
            <a-popconfirm :title="$t('shan-chu-zhang-hao-que-ren')" @confirm="handleDelete(record)">
              <a-button type="link" size="small" danger>{{ $t('shan-chu') }}</a-button>
            </a-popconfirm>
          </div>
        </template>
      </template>
      <template #emptyText>
        <div class="dmops-empty">{{ $t('zan-wu-shu-ju') }}</div>
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

    <AccountFormModal v-model:open="formOpen" :account="editingAccount" @saved="handleSaved" />
    <CredentialModal v-model:open="credentialOpen" :account="credentialAccount" @saved="handleSaved" />
  </div>
</template>

<script>
import Toast from '@/utils/toast';
import { deleteAccount, listAccounts, syncAccount } from '@/services/http/dmops';
import { credentialTypeLabel } from '@/views/dmops/utils/credential';
import AccountFormModal from './components/AccountFormModal';
import CredentialModal from './components/CredentialModal';

const PAGE_SIZE = 20;

export default {
  name: 'DmOpsAccountList',
  components: { AccountFormModal, CredentialModal },
  data() {
    return {
      loading: false,
      items: [],
      total: 0,
      page: 1,
      pageSize: PAGE_SIZE,
      filters: {
        keyword: '',
        enabled: ''
      },
      formOpen: false,
      editingAccount: null,
      credentialOpen: false,
      credentialAccount: null,
      syncingId: null
    };
  },
  computed: {
    columns() {
      return [
        { title: this.$t('a-li-yun-zhang-hao-id'), dataIndex: 'cloud_account_id', key: 'cloud_account_id', width: 190 },
        { title: this.$t('ming-cheng'), dataIndex: 'name', key: 'name', width: 180 },
        { title: this.$t('miao-shu'), dataIndex: 'description', key: 'description', ellipsis: true },
        { title: this.$t('mo-ren-di-qu'), dataIndex: 'default_region', key: 'default_region', width: 130 },
        { title: this.$t('ren-zheng-fang-shi'), key: 'credential', width: 150 },
        { title: this.$t('zhuang-tai'), key: 'enabled', width: 100 },
        { title: this.$t('zui-jin-tong-bu'), key: 'last_sync', width: 220 },
        { title: this.$t('cao-zuo'), key: 'actions', width: 280 }
      ];
    }
  },
  mounted() {
    this.load();
  },
  methods: {
    typeLabel(type) {
      return credentialTypeLabel(this.$t, type);
    },
    syncStatusLabel(status) {
      const labels = {
        SUCCESS: this.$t('cheng-gong'),
        PARTIAL: this.$t('bu-fen-shi-bai'),
        FAILED: this.$t('shi-bai')
      };
      return labels[status] || status || '';
    },
    syncStatusColor(status) {
      const colors = {
        SUCCESS: 'green',
        PARTIAL: 'orange',
        FAILED: 'red'
      };
      return colors[status] || 'default';
    },
    async load() {
      this.loading = true;
      try {
        const params = {
          page: this.page,
          page_size: this.pageSize
        };
        if (this.filters.keyword) {
          params.keyword = this.filters.keyword.trim();
        }
        if (this.filters.enabled !== '') {
          params.enabled = this.filters.enabled;
        }

        const data = await listAccounts(params);
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
    openCreate() {
      this.editingAccount = null;
      this.formOpen = true;
    },
    openEdit(record) {
      this.editingAccount = record;
      this.formOpen = true;
    },
    openCredential(record) {
      this.credentialAccount = record;
      this.credentialOpen = true;
    },
    handleSaved() {
      this.load();
    },
    async handleDelete(record) {
      try {
        await deleteAccount(record.id);
        Toast.success(this.$t('cao-zuo-cheng-gong'));
        if (this.items.length === 1 && this.page > 1) {
          this.page -= 1;
        }
        await this.load();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      }
    },
    async handleSync(record) {
      this.syncingId = record.id;
      try {
        const result = await syncAccount(record.id);
        const params = { created: result.created || 0, updated: result.updated || 0 };
        if (result.status === 'SUCCESS') {
          Toast.success(this.$t('tong-bu-wan-cheng', params));
        } else if (result.status === 'PARTIAL') {
          Toast.warning(this.$t('tong-bu-bu-fen-shi-bai', params));
        } else {
          Toast.error(this.$t('tong-bu-shi-bai', params));
        }
        await this.load();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.syncingId = null;
      }
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

  &__search {
    width: 260px;
  }

  &__status {
    width: 140px;
  }

  &__right {
    margin-left: auto;
  }
}

.dmops-table {
  :deep(.ant-table-cell) {
    vertical-align: middle;
  }
}

.dmops-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.dmops-sync {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.dmops-muted {
  color: var(--text-tertiary);
}

.dmops-empty {
  padding: 24px 0;
  color: var(--text-tertiary);
}

.dmops-pagination {
  display: flex;
  justify-content: flex-end;
}
</style>
