<template>
  <!--
    备份恢复发起弹窗。
    错误展示约定（设计文档 §2.3）：字段级错误（实例描述）在表单项下方标红，
    全局条件类错误（备份集可用性/并发约束/Serverless）在顶部 Alert 区一次列出。
  -->
  <a-modal :open="open" :title="$t('bei-fen-hui-fu')" :width="620" :mask-closable="false" @cancel="close">
    <a-spin :spinning="preflightLoading">
      <!-- 全局条件类错误（一期 4 项检测中非字段级的部分） -->
      <a-alert v-if="globalFailures.length" class="dmops-restore-alert" type="error" show-icon :message="$t('can-shu-jian-ce-wei-tong-guo')">
        <template #description>
          <ul class="dmops-restore-alert__list">
            <li v-for="(failure, index) in globalFailures" :key="index">{{ failure }}</li>
          </ul>
        </template>
      </a-alert>

      <a-form class="dmops-form" layout="vertical">
        <a-form-item :label="$t('yong-tu')">
          <a-select v-model:value="purpose" :disabled="true">
            <a-select-option value="drill">{{ $t('bei-fen-hui-fu-yan-lian') }}</a-select-option>
          </a-select>
        </a-form-item>

        <!-- 克隆实例预览：preflight 回填，只读展示 -->
        <div class="dmops-restore-preview">
          <div class="dmops-restore-preview__title">{{ $t('ke-long-shi-li-yu-lan') }}</div>
          <a-descriptions size="small" :column="1" class="dmops-restore-preview__body">
            <a-descriptions-item :label="$t('yuan-shi-li')">
              {{ sourceInstanceText }}
            </a-descriptions-item>
            <a-descriptions-item :label="$t('di-qu-ke-yong-qu')">{{ regionZoneText }}</a-descriptions-item>
            <a-descriptions-item :label="$t('xi-lie')">{{ previewText('category') }}</a-descriptions-item>
            <a-descriptions-item :label="$t('gui-ge')">{{ previewText('instance_class') }}</a-descriptions-item>
            <a-descriptions-item :label="$t('cun-chu-rong-liang')">{{ storageText }}</a-descriptions-item>
            <a-descriptions-item :label="$t('cun-chu-lei-xing')">{{ previewText('storage_type') }}</a-descriptions-item>
            <a-descriptions-item :label="$t('wang-luo')">{{ networkText }}</a-descriptions-item>
            <a-descriptions-item :label="$t('fu-fei-lei-xing')">{{ payTypeText }}</a-descriptions-item>
            <a-descriptions-item v-if="isServerless" :label="$t('rcu-kuo-rong-fan-wei')">
              {{ rcuRangeText }}
            </a-descriptions-item>
            <a-descriptions-item :label="$t('suo-yong-bei-fen-ji')">
              {{ backupText }}
            </a-descriptions-item>
          </a-descriptions>
        </div>

        <!-- 可编辑项：实例名称（DBInstanceDescription），预填模板 drill-{drill_no} 可改 -->
        <a-form-item
          :label="$t('shi-li-ming-cheng')"
          required
          :help="fieldErrors.instance_description || descriptionHint"
          :validate-status="fieldErrors.instance_description ? 'error' : ''"
        >
          <a-input
            v-model:value="form.instance_description"
            :maxlength="255"
            :placeholder="$t('shi-li-ming-cheng-zhan-wei')"
            @input="clearFieldError('instance_description')"
          />
        </a-form-item>

        <a-alert class="dmops-restore-alert" type="warning" show-icon :message="$t('ke-long-shi-li-ji-fei-ti-shi')" />
      </a-form>
    </a-spin>

    <template #footer>
      <a-button @click="close">{{ $t('qu-xiao') }}</a-button>
      <a-button type="primary" :loading="starting" :disabled="!preflight || !preflightPassed || preflightLoading" @click="submit">
        {{ $t('qi-dong-yan-lian') }}
      </a-button>
    </template>
  </a-modal>
</template>

<script>
import Toast from '@/utils/toast';
import { createBackupDrill, getDrillPreflight } from '@/services/http/dmops';
import { formatBytes } from '@/views/dmops/utils/instance';

export default {
  name: 'DmOpsBackupRestoreModal',
  props: {
    open: {
      type: Boolean,
      default: false
    },
    // 发起入口的上下文：实例路由参数 + 目标备份集行
    context: {
      type: Object,
      default: null
    }
  },
  emits: ['update:open', 'started'],
  data() {
    return {
      purpose: 'drill',
      preflightLoading: false,
      starting: false,
      preflight: null,
      form: {
        instance_description: ''
      },
      fieldErrors: {}
    };
  },
  computed: {
    instanceName() {
      return (this.context && this.context.instanceName) || '';
    },
    sourceInstanceText() {
      const id = (this.context && this.context.instanceId) || '-';
      return this.instanceName ? `${id} | ${this.instanceName}` : id;
    },
    regionZoneText() {
      const region = (this.context && this.context.region) || '';
      const zone = this.preview('zone_id');
      if (region && zone && zone !== '-') {
        return `${region} / ${zone}`;
      }
      return region || '-';
    },
    storageText() {
      const value = this.preview('storage_gb');
      if (value === '-' || value === null || value === undefined || value === '') {
        return '-';
      }
      return formatBytes(Number(value) * 1024 ** 3) || '-';
    },
    networkText() {
      const networkType = this.preview('network_type');
      const vpcId = this.preview('vpc_id');
      if (networkType === 'VPC' && vpcId && vpcId !== '-') {
        return `${this.$t('yuan-vpc')}: ${vpcId}`;
      }
      return networkType;
    },
    backupText() {
      const backup = this.context && this.context.backup;
      if (!backup) {
        return '-';
      }
      return `${backup.backup_id} | ${this.$t('bei-fen-wan-cheng')} ${this.localTime(backup.backup_end_time)}`;
    },
    isServerless() {
      const category = this.preview('category');
      return category !== '-' && category.toLowerCase().startsWith('serverless');
    },
    payTypeText() {
      if (this.isServerless) {
        return this.$t('serverless-fu-fei');
      }
      return this.$t('an-liang-fu-fei');
    },
    rcuRangeText() {
      const min = this.preview('serverless_min_capacity');
      const max = this.preview('serverless_max_capacity');
      if (min === '-' && max === '-') {
        return '-';
      }
      return `${min} ~ ${max} RCU`;
    },
    descriptionHint() {
      return this.$t('ming-cheng-gui-ze-ti-shi');
    },
    preflightPassed() {
      return !!(this.preflight && this.preflight.passed);
    },
    globalFailures() {
      const checks = (this.preflight && this.preflight.checks) || {};
      return Object.keys(checks)
        .filter((key) => !checks[key].passed)
        .map((key) => checks[key].message)
        .filter(Boolean);
    }
  },
  watch: {
    open(value) {
      if (value) {
        this.reset();
        this.loadPreflight();
      }
    }
  },
  methods: {
    preview(field) {
      const params = (this.preflight && this.preflight.clone_params_preview) || {};
      const value = params[field];
      if (value === null || value === undefined || value === '') {
        return '-';
      }
      return String(value);
    },
    localTime(value) {
      if (!value) {
        return '-';
      }
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return String(value);
      }
      const pad = (num) => String(num).padStart(2, '0');
      return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
        ` ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
      );
    },
    clearFieldError(field) {
      if (this.fieldErrors[field]) {
        this.fieldErrors = { ...this.fieldErrors, [field]: '' };
      }
    },
    reset() {
      this.form.instance_description = '';
      this.fieldErrors = {};
      this.preflight = null;
    },
    close() {
      this.$emit('update:open', false);
    },
    async loadPreflight() {
      const context = this.context;
      if (!context || !context.accountId || !context.region || !context.instanceId) {
        return;
      }
      this.preflightLoading = true;
      try {
        this.preflight = await getDrillPreflight(context.accountId, context.region, context.instanceId);
        // 预填模板 drill-{drill_no}（preflight 推算的预览号，可编辑）。
        if (this.preflight && this.preflight.next_drill_no) {
          this.form.instance_description = `drill-${this.preflight.next_drill_no}`;
        }
      } catch (error) {
        this.preflight = null;
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.preflightLoading = false;
      }
    },
    validate() {
      const description = String(this.form.instance_description || '').trim();
      // 阿里云 DBInstanceDescription 规则：字母或中文开头、2~255 字符，
      // 中文/字母/数字/下划线/短横线，不以 http 开头；留空则走后端模板。
      if (!description) {
        return true;
      }
      if (description.length < 2) {
        this.fieldErrors = {
          instance_description: this.$t('ming-cheng-zui-shao-ge-zi-fu')
        };
        return false;
      }
      if (description.toLowerCase().startsWith('http')) {
        this.fieldErrors = {
          instance_description: this.$t('ming-cheng-bu-neng-yi-http-kai-tou')
        };
        return false;
      }
      if (!/^[A-Za-z一-龥][A-Za-z0-9一-龥_-]*$/.test(description)) {
        this.fieldErrors = {
          instance_description: this.$t('ming-cheng-zi-fu-ji-he-fa')
        };
        return false;
      }
      return true;
    },
    async submit() {
      const context = this.context;
      if (!context || !this.preflightPassed || !this.validate()) {
        return;
      }
      this.starting = true;
      try {
        const data = await createBackupDrill({
          account_id: context.accountId,
          region: context.region,
          instance_id: context.instanceId,
          backup_id: context.backup && context.backup.backup_id,
          instance_description: String(this.form.instance_description || '').trim(),
          prefilled_drill_no: (this.preflight && this.preflight.next_drill_no) || ''
        });
        Toast.success(this.$t('yan-lian-yi-qi-dong', { drillNo: data.drill_no }));
        this.$emit('started', data);
        this.close();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.starting = false;
      }
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-restore-alert {
  margin-bottom: 12px;

  &__list {
    margin: 0;
    padding-left: 16px;
  }
}

.dmops-restore-preview {
  margin-bottom: 16px;

  &__title {
    margin-bottom: 8px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  &__body {
    padding: 8px 4px 4px 12px;
    background: var(--bg-secondary);
    border-radius: 4px;

    :deep(.ant-descriptions-item-label) {
      width: 104px;
      padding-right: 12px;
      white-space: nowrap;
    }

    :deep(.ant-descriptions-item-content) {
      padding-right: 8px;
      word-break: break-all;
    }
  }
}
</style>
