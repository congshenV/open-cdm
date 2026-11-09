<template>
  <div class="content-wrapper dmops-page">
    <div class="dmops-toolbar">
      <a-input
        v-model:value="filters.keyword"
        class="dmops-toolbar__search"
        :placeholder="$t('sou-suo-pei-zhi')"
        allow-clear
        @press-enter="handleSearch"
      />
      <a-select v-model:value="filters.scope" class="dmops-toolbar__scope" @change="handleSearch">
        <a-select-option value="">{{ $t('quan-bu-mo-kuai') }}</a-select-option>
        <a-select-option v-for="scope in scopes" :key="scope" :value="scope">{{ scope }}</a-select-option>
      </a-select>
      <a-button @click="handleSearch">{{ $t('cha-xun') }}</a-button>
      <div class="dmops-toolbar__right">
        <a-button type="primary" @click="openCreate">{{ $t('xin-jian-pei-zhi-xiang') }}</a-button>
      </div>
    </div>

    <a-table class="dmops-table" :columns="columns" :data-source="items" :loading="loading" :pagination="false" row-key="id" size="middle">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'config_scope'">
          <a-tag>{{ record.config_scope }}</a-tag>
        </template>
        <template v-else-if="column.key === 'config_type'">
          <a-tag>{{ record.config_type }}</a-tag>
        </template>
        <template v-else-if="column.key === 'config_value'">
          <span v-if="record.is_encrypt" class="dmops-masked">{{ MASKED_VALUE }}</span>
          <a-tooltip v-else :title="record.config_value" placement="topLeft">
            <span class="dmops-value">{{ record.config_value }}</span>
          </a-tooltip>
        </template>
        <template v-else-if="column.key === 'is_encrypt'">
          {{ record.is_encrypt ? $t('shi') : $t('fou') }}
        </template>
        <template v-else-if="column.key === 'actions'">
          <div class="dmops-actions">
            <a-button type="link" size="small" @click="openEdit(record)">{{ $t('bian-ji') }}</a-button>
            <a-popconfirm :title="$t('shan-chu-pei-zhi-que-ren')" @confirm="handleDelete(record)">
              <a-button type="link" size="small" danger>{{ $t('shan-chu') }}</a-button>
            </a-popconfirm>
          </div>
        </template>
      </template>
      <template #emptyText>
        <div class="dmops-empty">{{ $t('zan-wu-shu-ju') }}</div>
      </template>
    </a-table>

    <ConfigFormModal v-model:open="formOpen" :config="editingConfig" @saved="handleSaved" />
  </div>
</template>

<script>
import Toast from '@/utils/toast';
import { deleteConfig, listConfigs } from '@/services/http/dmops';
import ConfigFormModal from './components/ConfigFormModal';

// 与后端 config_service 的 CONFIG_SCOPES 和 MASKED_VALUE 保持一致
const SCOPES = ['base', 'rds', 'redis'];
const MASKED_VALUE = '******';

export default {
  name: 'DmOpsConfigManage',
  components: { ConfigFormModal },
  data() {
    return {
      MASKED_VALUE,
      scopes: SCOPES,
      loading: false,
      items: [],
      filters: {
        keyword: '',
        scope: ''
      },
      formOpen: false,
      editingConfig: null
    };
  },
  computed: {
    columns() {
      return [
        { title: this.$t('pei-zhi-ming'), dataIndex: 'config_name', key: 'config_name', width: 160 },
        { title: this.$t('mo-kuai'), key: 'config_scope', width: 100 },
        { title: this.$t('pei-zhi-jian'), dataIndex: 'config_key', key: 'config_key', width: 200 },
        { title: this.$t('shu-ju-lei-xing'), key: 'config_type', width: 110 },
        { title: this.$t('pei-zhi-zhi'), key: 'config_value', ellipsis: true },
        { title: this.$t('shi-fou-jia-mi'), key: 'is_encrypt', width: 90 },
        { title: this.$t('chuang-jian-ren'), dataIndex: 'create_user', key: 'create_user', width: 120 },
        { title: this.$t('miao-shu'), dataIndex: 'description', key: 'description', ellipsis: true },
        { title: this.$t('geng-xin-shi-jian'), dataIndex: 'updated_at', key: 'updated_at', width: 170 },
        { title: this.$t('cao-zuo'), key: 'actions', width: 130 }
      ];
    }
  },
  mounted() {
    this.load();
  },
  methods: {
    // 配置项数量有限，全量加载不分页
    async load() {
      this.loading = true;
      try {
        const params = {};
        if (this.filters.keyword) {
          params.keyword = this.filters.keyword.trim();
        }
        if (this.filters.scope) {
          params.scope = this.filters.scope;
        }

        const data = await listConfigs(params);
        this.items = data || [];
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.loading = false;
      }
    },
    handleSearch() {
      this.load();
    },
    openCreate() {
      this.editingConfig = null;
      this.formOpen = true;
    },
    openEdit(record) {
      this.editingConfig = record;
      this.formOpen = true;
    },
    handleSaved() {
      this.load();
    },
    async handleDelete(record) {
      try {
        await deleteConfig(record.id);
        Toast.success(this.$t('cao-zuo-cheng-gong'));
        await this.load();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
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

  &__scope {
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

.dmops-value {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.dmops-masked {
  color: var(--text-tertiary);
  font-family: monospace;
}

.dmops-empty {
  padding: 24px 0;
  color: var(--text-tertiary);
}
</style>
