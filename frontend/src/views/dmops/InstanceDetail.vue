<template>
  <!-- 实例详情：第一个 Tab 展示完整实例信息，第二个 Tab 展示备份策略与备份列表 -->
  <div class="content-wrapper dmops-detail">
    <div class="dmops-detail-bar">
      <a-button type="link" class="dmops-detail-back" @click="goList">
        <CustomIcon type="icon-v2-ArrowLeftSimple" size="14px" />
        <span>{{ $t('fan-hui-shi-li-lie-biao') }}</span>
      </a-button>
    </div>

    <a-tabs v-model:activeKey="activeTab" class="dmops-detail-tabs">
      <a-tab-pane key="detail" :tab="$t('shi-li-xiang-qing')">
        <a-spin :spinning="loading">
          <a-result v-if="loadError" status="error" :title="$t('yun-wei-jie-kou-diao-yong-shi-bai')" :sub-title="loadError">
            <template #extra>
              <a-button @click="loadDetail">{{ $t('shua-xin') }}</a-button>
            </template>
          </a-result>

          <template v-else-if="detail">
            <a-descriptions size="middle" :column="{ xs: 1, sm: 2, lg: 3 }" :title="$t('ji-chu-xin-xi')" class="dmops-descriptions">
              <a-descriptions-item :label="$t('shi-li-ming-cheng')">{{ text(detail.instance_name) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('shi-li-id')">{{ text(detail.instance_id) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('zhang-hao')">{{ accountText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('di-qu')">{{ text(detail.region) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('ke-yong-qu')">{{ text(detail.zone_id) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('zhuang-tai')">
                <a-tag v-if="detail.status" :color="statusColor(detail.status)">{{ statusLabel(detail.status) }}</a-tag>
                <span v-else>-</span>
              </a-descriptions-item>
              <a-descriptions-item :label="$t('shi-li-lei-xing')">{{ instanceTypeText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('shi-li-xi-lie')">{{ categoryText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('owner')">{{ text(detail.owner) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('level')">{{ text(detail.level) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('prodline')">{{ text(detail.prodline) }}</a-descriptions-item>
            </a-descriptions>

            <a-descriptions size="middle" :column="{ xs: 1, sm: 2, lg: 3 }" :title="$t('gui-ge-xin-xi')" class="dmops-descriptions">
              <a-descriptions-item :label="$t('shu-ju-ku-lei-xing')">{{ engineText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('shi-li-gui-ge')">{{ text(detail.instance_class) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('cpu-he-shu')">{{ cpuText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('nei-cun')">{{ memoryText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('cun-chu-rong-liang')">{{ storageText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('ci-pan-yi-yong-liang')">{{ diskUsedText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('ci-pan-shui-wei')">{{ diskPercentText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('cun-chu-lei-xing')">{{ text(detail.storage_type) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('fu-fei-fang-shi')">{{ payTypeText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('wang-luo-lei-xing')">{{ networkTypeText }}</a-descriptions-item>
            </a-descriptions>

            <a-descriptions size="middle" :column="{ xs: 1, sm: 2, lg: 3 }" :title="$t('wang-luo-xin-xi')" class="dmops-descriptions">
              <a-descriptions-item :label="$t('lian-jie-di-zhi')">{{ text(detail.connection_string) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('duan-kou')">{{ text(detail.port) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('vpc-id')">{{ text(detail.vpc_id) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('vswitch-id')">{{ text(detail.vswitch_id) }}</a-descriptions-item>
            </a-descriptions>

            <a-descriptions size="middle" :column="{ xs: 1, sm: 2, lg: 3 }" :title="$t('qi-ta-xin-xi')" class="dmops-descriptions">
              <a-descriptions-item :label="$t('chuang-jian-shi-jian')">{{ text(detail.create_time) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('guo-qi-shi-jian')">{{ text(detail.expire_time) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('suo-ding')">{{ lockModeText }}</a-descriptions-item>
              <a-descriptions-item :label="$t('suo-ding-yuan-yin')">{{ text(detail.lock_reason) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('shan-chu-bao-hu')">{{ boolText(detail.deletion_protection) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('zhu-shi-li-id')">{{ text(detail.master_instance_id) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('zai-bei-shi-li-id')">{{ text(detail.guard_instance_id) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('lin-shi-shi-li-id')">{{ text(detail.temp_instance_id) }}</a-descriptions-item>
              <a-descriptions-item :label="$t('du-shi-li-id')" :span="3">{{ readonlyText }}</a-descriptions-item>
            </a-descriptions>
          </template>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="backup" :tab="$t('bei-fen-xiang-qing')">
        <div class="dmops-backup">
          <!-- 备份策略 -->
          <a-alert class="dmops-policy-hint" type="warning" show-icon :message="$t('bei-fen-ce-lue-xi-shu-ti-shi')" />
          <a-spin :spinning="policyLoading">
            <a-result v-if="policyError" status="error" :title="$t('yun-wei-jie-kou-diao-yong-shi-bai')" :sub-title="policyError">
              <template #extra>
                <a-button @click="loadPolicy">{{ $t('shua-xin') }}</a-button>
              </template>
            </a-result>

            <template v-else-if="policy">
              <!-- 备份策略：三个横向卡片 -->
              <div class="dmops-policy-cards">
                <!-- 卡片一：本地日志保留策略 -->
                <div class="dmops-policy-card">
                  <div class="dmops-policy-card__title">{{ $t('ben-di-ri-zhi-bao-liu-ce-lue') }}</div>
                  <a-descriptions size="small" :column="1" class="dmops-policy-card__body">
                    <a-descriptions-item :label="$t('bao-liu-shi-chang')">{{ hoursText(policy.local_log_retention_hours) }}</a-descriptions-item>
                    <a-descriptions-item :label="$t('wen-jian-bao-liu-ge-shu')">
                      {{ countText(policy.log_backup_local_retention_number) }}
                    </a-descriptions-item>
                    <a-descriptions-item :label="$t('zui-da-cun-chu-kong-jian-zhan-you-lv')">
                      {{ percentText(policy.local_log_retention_space) }}
                    </a-descriptions-item>
                  </a-descriptions>
                </div>

                <!-- 卡片二：本地备份 -->
                <div class="dmops-policy-card">
                  <div class="dmops-policy-card__title">{{ $t('ben-di-bei-fen') }}</div>
                  <a-descriptions size="small" :column="1" class="dmops-policy-card__body">
                    <a-descriptions-item :label="$t('bei-fen-zhou-qi')">{{ backupPeriodText }}</a-descriptions-item>
                    <a-descriptions-item :label="$t('shu-ju-bei-fen-bao-liu')">{{ daysText(policy.backup_retention_period) }}</a-descriptions-item>
                    <a-descriptions-item :label="$t('ri-zhi-bei-fen-bao-liu')">
                      {{ daysText(policy.log_backup_retention_period) }}
                    </a-descriptions-item>
                  </a-descriptions>
                </div>

                <!-- 卡片三：异地备份 -->
                <div class="dmops-policy-card">
                  <div class="dmops-policy-card__title">{{ $t('yi-di-bei-fen') }}</div>
                  <a-descriptions size="small" :column="1" class="dmops-policy-card__body">
                    <template v-if="policy.cross_error">
                      <a-descriptions-item :label="$t('yi-di-bei-fen-kai-qi')">
                        <a-tooltip :title="policy.cross_error">
                          <span class="dmops-muted">{{ $t('wei-zhi') }}</span>
                        </a-tooltip>
                      </a-descriptions-item>
                    </template>
                    <template v-else>
                      <a-descriptions-item :label="$t('yi-di-bei-fen-kai-qi')">
                        {{ boolText(crossPolicy && crossPolicy.backup_enabled) }}
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('yi-di-ri-zhi-bei-fen-kai-qi')">
                        {{ boolText(crossPolicy && crossPolicy.log_backup_enabled) }}
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('yi-di-mu-di-di')">
                        {{ text(crossPolicy && crossPolicy.cross_backup_region) }}
                      </a-descriptions-item>
                      <a-descriptions-item :label="$t('yi-di-bao-liu-tian-shu')">
                        {{ daysText(crossPolicy && crossPolicy.retention_days) }}
                      </a-descriptions-item>
                    </template>
                  </a-descriptions>
                </div>
              </div>
            </template>
          </a-spin>

          <!-- 备份列表：备份集 / 日志备份 -->
          <a-tabs v-model:activeKey="backupListTab" size="small" class="dmops-backup-list">
            <a-tab-pane key="set" :tab="$t('bei-fen-ji')">
              <a-table
                class="dmops-backup-table"
                :columns="backupColumns"
                :data-source="backupItems"
                :loading="backupLoading"
                :pagination="false"
                row-key="backup_id"
                size="small"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'status'">
                    <a-tag :color="backupStatusColor(record.backup_status)">{{ backupStatusLabel(record.backup_status) }}</a-tag>
                  </template>
                  <template v-else-if="column.key === 'start_end'">
                    <div class="dmops-stack">
                      <span class="dmops-stack__main">{{ localTime(record.backup_start_time) }}</span>
                      <span v-if="record.backup_end_time" class="dmops-stack__sub">{{ localTime(record.backup_end_time) }}</span>
                    </div>
                  </template>
                  <template v-else-if="column.key === 'type'">
                    {{ backupTypeLabel(record.backup_type) }} / {{ backupMethodLabel(record.backup_method) }}
                  </template>
                  <template v-else-if="column.key === 'mode'">
                    <span :class="record.backup_mode === 'Manual' ? 'dmops-badge-manual' : 'dmops-badge-auto'">
                      {{ backupModeLabel(record.backup_mode) }}
                    </span>
                  </template>
                  <template v-else-if="column.key === 'size'">
                    {{ sizeText(record.backup_size) }}
                  </template>
                  <template v-else-if="column.key === 'is_avail'">
                    <a-tag :color="record.is_avail === 1 ? 'green' : 'default'">
                      {{ boolText(record.is_avail === 1) }}
                    </a-tag>
                  </template>
                  <template v-else-if="column.key === 'actions'">
                    <!-- 备份恢复入口常驻（同备份集可多次发起）；已有演练时追加演练链接（10s 轮询推进状态） -->
                    <!-- 左：常驻备份恢复按钮；右：演练任务链接每行一个 -->
                    <div class="dmops-restore-cell">
                      <div class="dmops-restore-cell__action">
                        <a-tooltip v-if="record.is_avail !== 1" :title="$t('gai-bei-fen-ji-bu-ke-yong')">
                          <a-button size="small" disabled>{{ $t('bei-fen-hui-fu') }}</a-button>
                        </a-tooltip>
                        <a-button v-else size="small" @click="openRestoreModal(record)">
                          {{ $t('bei-fen-hui-fu') }}
                        </a-button>
                      </div>
                      <div v-if="drillsByBackupId(record.backup_id).length" class="dmops-restore-cell__tasks">
                        <a-tooltip v-for="drill in drillsByBackupId(record.backup_id)" :key="drill.id" :title="drillBadgeTooltip(drill)">
                          <a class="dmops-restore-task" :class="{ 'is-active': isDrillActive(drill.status) }" @click="openDrillDetail(drill)">
                            <loading-outlined v-if="isDrillActive(drill.status)" spin />
                            {{ $t('bei-fen-hui-fu-ren-wu') }}{{ drill.drill_no }}
                          </a>
                        </a-tooltip>
                      </div>
                    </div>
                  </template>
                </template>
              </a-table>
              <div v-if="backupTotal > 0" class="dmops-pagination">
                <Page
                  :total="backupTotal"
                  :page-size="backupPageSize"
                  :model-value="backupPage"
                  show-total
                  :page-size-opts="[30, 50, 100]"
                  @on-change="handleBackupPageChange"
                  @on-page-size-change="handleBackupPageSizeChange"
                />
              </div>
            </a-tab-pane>

            <a-tab-pane key="log" :tab="$t('ri-zhi-bei-fen')">
              <div class="dmops-binlog-toolbar">
                <span class="dmops-binlog-toolbar__label">{{ $t('bei-fen-shi-li-bian-hao') }}</span>
                <a-select v-model:value="binlogHostFilter" allow-clear style="width: 140px" :placeholder="$t('quan-bu')">
                  <a-select-option v-for="host in binlogHosts" :key="host" :value="host">{{ host }}</a-select-option>
                </a-select>
                <span class="dmops-binlog-toolbar__label">{{ $t('zui-jin') }}</span>
                <span class="dmops-binlog-toolbar__label">{{ $t('zui-jin') }}</span>
                <a-select v-model:value="binlogDays" style="width: 120px" @change="handleBinlogDaysChange">
                  <a-select-option v-for="day in [1, 7, 30]" :key="day" :value="day">{{ day }} {{ $t('tian-shu-dan-wei') }}</a-select-option>
                </a-select>
                <a-button :loading="binlogLoading" @click="loadBinlog">{{ $t('cha-xun') }}</a-button>
              </div>
              <a-table
                class="dmops-backup-table"
                :columns="binlogColumns"
                :data-source="filteredBinlogItems"
                :loading="binlogLoading"
                :pagination="false"
                row-key="checksum"
                size="small"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'status'">
                    <a-tag :color="record.remote_status === 'Completed' ? 'green' : 'blue'">
                      {{ binlogStatusLabel(record.remote_status) }}
                    </a-tag>
                  </template>
                  <template v-else-if="column.key === 'begin'">
                    {{ localTime(record.log_begin_time) }}
                  </template>
                  <template v-else-if="column.key === 'end'">
                    {{ localTime(record.log_end_time) }}
                  </template>
                  <template v-else-if="column.key === 'size'">
                    {{ sizeText(record.file_size) }}
                  </template>
                </template>
              </a-table>
              <div v-if="binlogTotal > 0" class="dmops-pagination">
                <Page
                  :total="binlogTotal"
                  :page-size="binlogPageSize"
                  :model-value="binlogPage"
                  show-total
                  :page-size-opts="[30, 50, 100]"
                  @on-change="handleBinlogPageChange"
                  @on-page-size-change="handleBinlogPageSizeChange"
                />
              </div>
            </a-tab-pane>

            <a-tab-pane key="crossSet" :tab="$t('yi-di-bei-fen-ji-0')">
              <div class="dmops-binlog-toolbar">
                <span class="dmops-binlog-toolbar__label">{{ $t('zui-jin') }}</span>
                <a-select v-model:value="crossDays" style="width: 120px" @change="handleCrossDaysChange">
                  <a-select-option v-for="day in [1, 7, 30]" :key="day" :value="day">{{ day }} {{ $t('tian-shu-dan-wei') }}</a-select-option>
                </a-select>
                <a-button :loading="crossBackupLoading" @click="loadCrossBackups">{{ $t('cha-xun') }}</a-button>
              </div>
              <a-table
                class="dmops-backup-table"
                :columns="crossBackupColumns"
                :data-source="crossBackupItems"
                :loading="crossBackupLoading"
                :pagination="false"
                row-key="cross_backup_id"
                size="small"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'status'">
                    <a-tag :color="record.backup_set_status === 0 ? 'green' : 'red'">
                      {{ crossStatusText(record.backup_set_status) }}
                    </a-tag>
                  </template>
                  <template v-else-if="column.key === 'start_end'">
                    <div class="dmops-stack">
                      <span class="dmops-stack__main">{{ localTime(record.backup_start_time) }}</span>
                      <span v-if="record.backup_end_time" class="dmops-stack__sub">{{ localTime(record.backup_end_time) }}</span>
                    </div>
                  </template>
                  <template v-else-if="column.key === 'type'">
                    {{ crossBackupTypeLabel(record.backup_type) }} / {{ crossBackupMethodLabel(record.backup_method) }}
                  </template>
                  <template v-else-if="column.key === 'size'">
                    {{ formatBytes(record.cross_backup_set_size) || '-' }}
                  </template>
                  <template v-else-if="column.key === 'actions'">
                    <a v-if="record.cross_backup_download_link" :href="record.cross_backup_download_link" target="_blank" rel="noopener noreferrer">
                      {{ $t('xia-zai-bei-fen') }}
                    </a>
                    <span v-else class="dmops-muted">-</span>
                  </template>
                </template>
              </a-table>
              <div v-if="crossBackupTotal > 0" class="dmops-pagination">
                <Page
                  :total="crossBackupTotal"
                  :page-size="crossBackupPageSize"
                  :model-value="crossBackupPage"
                  show-total
                  :page-size-opts="[30, 50, 100]"
                  @on-change="handleCrossBackupPageChange"
                  @on-page-size-change="handleCrossBackupPageSizeChange"
                />
              </div>
            </a-tab-pane>

            <a-tab-pane key="crossLog" :tab="$t('yi-di-ri-zhi-bei-fen-0')">
              <div class="dmops-binlog-toolbar">
                <span class="dmops-binlog-toolbar__label">{{ $t('zui-jin') }}</span>
                <a-select v-model:value="crossLogDays" style="width: 120px" @change="handleCrossLogDaysChange">
                  <a-select-option v-for="day in [1, 7, 30]" :key="day" :value="day">{{ day }} {{ $t('tian-shu-dan-wei') }}</a-select-option>
                </a-select>
                <a-button :loading="crossLogLoading" @click="loadCrossLogs">{{ $t('cha-xun') }}</a-button>
              </div>
              <a-table
                class="dmops-backup-table"
                :columns="crossLogColumns"
                :data-source="crossLogItems"
                :loading="crossLogLoading"
                :pagination="false"
                row-key="cross_log_backup_id"
                size="small"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'start_end'">
                    <div class="dmops-stack">
                      <span class="dmops-stack__main">{{ localTime(record.log_begin_time) }}</span>
                      <span v-if="record.log_end_time" class="dmops-stack__sub">{{ localTime(record.log_end_time) }}</span>
                    </div>
                  </template>
                  <template v-else-if="column.key === 'size'">
                    {{ formatBytes(record.file_size) || '-' }}
                  </template>
                  <template v-else-if="column.key === 'actions'">
                    <a v-if="record.download_link" :href="record.download_link" target="_blank" rel="noopener noreferrer">
                      {{ $t('xia-zai-ri-zhi-wen-jian') }}
                    </a>
                    <span v-else class="dmops-muted">-</span>
                  </template>
                </template>
              </a-table>
              <div v-if="crossLogTotal > 0" class="dmops-pagination">
                <Page
                  :total="crossLogTotal"
                  :page-size="crossLogPageSize"
                  :model-value="crossLogPage"
                  show-total
                  :page-size-opts="[30, 50, 100]"
                  @on-change="handleCrossLogPageChange"
                  @on-page-size-change="handleCrossLogPageSizeChange"
                />
              </div>
            </a-tab-pane>
          </a-tabs>
        </div>
      </a-tab-pane>
    </a-tabs>

    <!-- 备份恢复发起弹窗 -->
    <BackupRestoreModal v-model:open="restoreOpen" :context="restoreContext" @started="handleDrillStarted" />
  </div>
</template>

<script>
import Toast from '@/utils/toast';
import { LoadingOutlined } from '@ant-design/icons-vue';
import {
  getBackupPolicy,
  getInstanceDetail,
  listBackupDrills,
  listBackups,
  listBinlogFiles,
  listCrossRegionBackups,
  listCrossRegionLogBackupFiles
} from '@/services/http/dmops';
import {
  categoryLabel,
  formatBytes,
  instanceTypeLabel,
  networkTypeLabel,
  payTypeLabel,
  statusColor,
  statusLabel
} from '@/views/dmops/utils/instance';
import { backupLabels } from '@/views/dmops/utils/backup';
import { drillLabels, isDrillActive } from '@/views/dmops/utils/drill';
import BackupRestoreModal from '@/views/dmops/components/BackupRestoreModal';

const LOCK_MODE_KEYS = {
  Locked: 'yi-suo-ding',
  Unlock: 'wei-suo-ding'
};

// 日志备份默认查最近 7 天。
const BINLOG_DEFAULT_DAYS = 7;

// 备份集行内演练徽标轮询间隔（仅存在未终态演练时启动）。
const DRILL_POLL_INTERVAL_MS = 10000;

export default {
  name: 'DmOpsInstanceDetail',
  components: { BackupRestoreModal, LoadingOutlined },
  mixins: [backupLabels, drillLabels],
  data() {
    return {
      activeTab: 'detail',
      loading: false,
      loadError: '',
      detail: null,
      // 备份策略
      policyLoading: false,
      policyError: '',
      policy: null,
      // 备份集列表
      backupListTab: 'set',
      backupLoading: false,
      backupItems: [],
      backupTotal: 0,
      backupPage: 1,
      // DescribeBackups 的 PageSize 只允许 30/50/100。
      backupPageSize: 30,
      // 日志备份列表
      binlogLoading: false,
      binlogItems: [],
      binlogTotal: 0,
      binlogPage: 1,
      // DescribeBinlogFiles 的 PageSize 允许 30~100。
      binlogPageSize: 30,
      binlogDays: BINLOG_DEFAULT_DAYS,
      // 备份实例编号前端过滤（区分主备库产生的日志）
      binlogHostFilter: undefined,
      // 跨地域备份集列表
      crossBackupLoading: false,
      crossBackupItems: [],
      crossBackupTotal: 0,
      crossBackupPage: 1,
      crossBackupPageSize: 30,
      crossDays: BINLOG_DEFAULT_DAYS,
      // 跨地域日志备份列表
      crossLogLoading: false,
      crossLogItems: [],
      crossLogTotal: 0,
      crossLogPage: 1,
      crossLogPageSize: 30,
      crossLogDays: BINLOG_DEFAULT_DAYS,
      // 备份恢复演练
      restoreOpen: false,
      restoreContext: null,
      drills: [],
      drillPollTimer: null
    };
  },
  computed: {
    accountText() {
      if (!this.detail) {
        return '-';
      }
      const name = this.detail.account_name || '';
      const id = this.detail.cloud_account_id || '';
      if (name && id) {
        return `${name} (${id})`;
      }
      return name || id || '-';
    },
    engineText() {
      if (!this.detail || !this.detail.engine) {
        return '-';
      }
      return this.detail.engine_version ? `${this.detail.engine} ${this.detail.engine_version}` : this.detail.engine;
    },
    cpuText() {
      return this.detail && this.detail.cpu ? `${this.detail.cpu} ${this.$t('he')}` : '-';
    },
    memoryText() {
      const value = this.detail && this.detail.memory_mb;
      if (value === null || value === undefined || value === '') {
        return '-';
      }
      return formatBytes(Number(value) * 1024 * 1024) || '-';
    },
    storageText() {
      const value = this.detail && this.detail.storage_gb;
      if (value === null || value === undefined || value === '') {
        return '-';
      }
      return formatBytes(Number(value) * 1024 ** 3) || '-';
    },
    diskUsedText() {
      const value = this.detail && this.detail.disk_used_bytes;
      if (value === null || value === undefined || value === '') {
        return '-';
      }
      return formatBytes(value) || '-';
    },
    diskPercentText() {
      const percent = this.detail && this.detail.disk_usage_percent;
      return percent === null || percent === undefined ? '-' : `${percent}%`;
    },
    instanceTypeText() {
      return this.detail ? instanceTypeLabel(this.$t, this.detail.instance_type) || '-' : '-';
    },
    categoryText() {
      return this.detail ? categoryLabel(this.$t, this.detail.category) || '-' : '-';
    },
    payTypeText() {
      return this.detail ? payTypeLabel(this.$t, this.detail.pay_type) || '-' : '-';
    },
    networkTypeText() {
      return this.detail ? networkTypeLabel(this.$t, this.detail.network_type) || '-' : '-';
    },
    lockModeText() {
      const mode = this.detail && this.detail.lock_mode;
      if (!mode) {
        return '-';
      }
      return LOCK_MODE_KEYS[mode] ? this.$t(LOCK_MODE_KEYS[mode]) : mode;
    },
    readonlyText() {
      const ids = this.detail && this.detail.readonly_instance_ids;
      return Array.isArray(ids) && ids.length ? ids.join(', ') : '-';
    },
    backupColumns() {
      return [
        { title: this.$t('bei-fen-id'), dataIndex: 'backup_id', key: 'backup_id', width: 75 },
        { title: this.$t('zhuang-tai'), key: 'status', width: 55 },
        { title: this.$t('bei-fen-shi-jian-dai'), key: 'start_end', width: 120 },
        { title: this.$t('bei-fen-lei-xing'), key: 'type', width: 110 },
        { title: this.$t('bei-fen-mo-shi'), key: 'mode', width: 80 },
        { title: this.$t('wen-jian-da-xiao'), key: 'size', width: 100 },
        { title: this.$t('shi-fou-ke-yong'), key: 'is_avail', width: 90 },
        { title: this.$t('cao-zuo'), key: 'actions', width: 220 }
      ];
    },
    binlogColumns() {
      // 日志文件名形如 mysql-bin.000339，时间为北京时间串
      return [
        { title: this.$t('ri-zhi-ming-cheng'), dataIndex: 'log_file_name', key: 'log_file_name', width: 130 },
        { title: this.$t('zhuang-tai'), key: 'status', width: 80 },
        { title: this.$t('ri-zhi-qi-shi-shi-jian'), key: 'begin', width: 170 },
        { title: this.$t('ri-zhi-jie-shu-shi-jian'), key: 'end', width: 170 },
        { title: this.$t('wen-jian-da-xiao'), key: 'size', width: 100 },
        { title: this.$t('bei-fen-shi-li-bian-hao'), dataIndex: 'host_instance_id', key: 'host_instance_id', width: 110 }
      ];
    },
    crossBackupColumns() {
      // 跨地域备份 ID 约为 8 位数字，文件名形如 cn-beijing_rm-***.zip
      return [
        { title: this.$t('yi-di-bei-fen-id'), dataIndex: 'cross_backup_id', key: 'cross_backup_id', width: 110 },
        { title: this.$t('zhuang-tai'), key: 'status', width: 90 },
        { title: this.$t('bei-fen-shi-jian-dai'), key: 'start_end', width: 190 },
        { title: this.$t('bei-fen-lei-xing'), key: 'type', width: 160 },
        { title: this.$t('bei-fen-wen-jian'), dataIndex: 'cross_backup_set_file', key: 'cross_backup_set_file' },
        { title: this.$t('yi-di-wen-jian-da-xiao'), key: 'size', width: 100 },
        { title: this.$t('cao-zuo'), key: 'actions', width: 110 }
      ];
    },
    crossLogColumns() {
      return [
        { title: this.$t('yi-di-bei-fen-id'), dataIndex: 'cross_log_backup_id', key: 'cross_log_backup_id', width: 110 },
        { title: this.$t('ri-zhi-ming-cheng'), dataIndex: 'log_file_name', key: 'log_file_name' },
        { title: this.$t('ri-zhi-qi-shi-shi-jian'), key: 'start_end', width: 190 },
        { title: this.$t('yi-di-wen-jian-da-xiao'), key: 'size', width: 100 },
        { title: this.$t('cao-zuo'), key: 'actions', width: 110 }
      ];
    },
    binlogHosts() {
      // 当前页日志数据里出现过的实例编号，去重排序
      const hosts = new Set(
        this.binlogItems.map((item) => item.host_instance_id).filter((host) => host !== '' && host !== undefined && host !== null)
      );
      return [...hosts].sort();
    },
    filteredBinlogItems() {
      if (!this.binlogHostFilter) {
        return this.binlogItems;
      }
      return this.binlogItems.filter((item) => item.host_instance_id === this.binlogHostFilter);
    },
    crossPolicy() {
      // 后端把跨地域设置合并在 policy.cross 里；查询失败时为关闭态并提示 cross_error
      return (this.policy && this.policy.cross) || null;
    },
    crossBackupEnabled() {
      // 策略未加载或异地备份未开启/状态未知时都不调异地接口
      return Boolean(this.crossPolicy && this.crossPolicy.backup_enabled);
    },
    backupPeriodText() {
      const value = this.policy && this.policy.preferred_backup_period;
      if (!value) {
        return '-';
      }
      return value
        .split(',')
        .map((item) => this.weekdayLabel(item.trim()))
        .filter(Boolean)
        .join('、');
    },
    crossStatusText() {
      return (status) => {
        if (status === 0) {
          return this.$t('zhuan-chu-wan-cheng');
        }
        if (status === 1) {
          return this.$t('zhuan-chu-shi-bai');
        }
        return '-';
      };
    }
  },
  watch: {
    '$route.params.instanceId'() {
      this.loadDetail();
    },
    activeTab(tab) {
      // 懒加载：首次切到备份 Tab 时才请求策略与备份集。
      if (tab === 'backup') {
        this.loadPolicy();
        if (!this.backupItems.length && !this.backupLoading) {
          this.loadBackups();
        }
        this.loadDrills();
      }
    },
    backupListTab(tab) {
      if (tab === 'log' && !this.binlogItems.length && !this.binlogLoading) {
        this.loadBinlog();
      }
      // 异地备份未开启（或状态未知）时不调接口，直接显示空列表
      if (tab === 'crossSet' && !this.crossBackupItems.length && !this.crossBackupLoading) {
        this.loadCrossBackups();
      }
      if (tab === 'crossLog' && !this.crossLogItems.length && !this.crossLogLoading) {
        this.loadCrossLogs();
      }
    }
  },
  mounted() {
    this.loadDetail();
  },
  beforeUnmount() {
    this.stopDrillPolling();
  },
  methods: {
    sizeText(value) {
      // 接口单位为字节，可能返回字符串或数字，这里统一转数字后自适应 B/KB/MB/GB/TB
      if (value === null || value === undefined || value === '') {
        return '-';
      }
      return formatBytes(Number(value)) || '-';
    },
    localTime(value) {
      // 阿里云返回 UTC 时间串（2026-11-02T19:13:32Z），转成浏览器本地时区展示
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
    text(value) {
      return value === null || value === undefined || value === '' ? '-' : String(value);
    },
    boolText(value) {
      if (value === true) {
        return this.$t('shi');
      }
      if (value === false) {
        return this.$t('fou');
      }
      return '-';
    },
    daysText(value) {
      return value === null || value === undefined || value === '' ? '-' : `${value} ${this.$t('tian-shu-dan-wei')}`;
    },
    hoursText(value) {
      return value === null || value === undefined || value === '' ? '-' : `${value} ${this.$t('xiao-shi-dan-wei')}`;
    },
    countText(value) {
      return value === null || value === undefined || value === '' ? '-' : String(value);
    },
    percentText(value) {
      return value === null || value === undefined || value === '' ? '-' : `${value}%`;
    },
    policyEnabled(value) {
      // BackupLog / HighSpaceUsageProtection 等字段用 Enable / Disabled 表示开关。
      if (value === 'Enable') {
        return true;
      }
      if (value === 'Disabled') {
        return false;
      }
      return null;
    },
    statusLabel(value) {
      return statusLabel(this.$t, value);
    },
    statusColor(value) {
      return statusColor(value);
    },
    goList() {
      this.$router.push('/dmops/instance').catch(() => {});
    },
    async loadDetail() {
      const accountId = Number(this.$route.query.account_id);
      const region = this.$route.query.region || '';
      const instanceId = this.$route.params.instanceId || '';
      if (!accountId || !region || !instanceId) {
        this.detail = null;
        this.loadError = this.$t('shi-li-can-shu-bu-wan-zheng');
        return;
      }

      this.loading = true;
      this.loadError = '';
      try {
        this.detail = await getInstanceDetail(accountId, region, instanceId);
      } catch (error) {
        this.detail = null;
        this.loadError = error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai');
        Toast.error(this.loadError);
      } finally {
        this.loading = false;
      }
    },
    async loadPolicy() {
      const { accountId, region, instanceId } = this.routeParams();
      if (!accountId || !region || !instanceId) {
        this.policy = null;
        this.policyError = this.$t('shi-li-can-shu-bu-wan-zheng');
        return;
      }
      // 已加载成功过就不再重复请求
      if (this.policy) {
        return;
      }
      this.policyLoading = true;
      this.policyError = '';
      try {
        this.policy = await getBackupPolicy(accountId, region, instanceId);
      } catch (error) {
        this.policy = null;
        this.policyError = error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai');
      } finally {
        this.policyLoading = false;
      }
    },
    async loadBackups() {
      const { accountId, region, instanceId } = this.routeParams();
      if (!accountId || !region || !instanceId || this.backupLoading) {
        return;
      }
      this.backupLoading = true;
      try {
        const data = await listBackups(accountId, region, instanceId, {
          page: this.backupPage,
          page_size: this.backupPageSize
        });
        this.backupItems = data.items || [];
        this.backupTotal = data.total || 0;
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.backupLoading = false;
      }
    },
    async loadBinlog() {
      const { accountId, region, instanceId } = this.routeParams();
      if (!accountId || !region || !instanceId || this.binlogLoading) {
        return;
      }
      this.binlogLoading = true;
      try {
        const data = await listBinlogFiles(accountId, region, instanceId, {
          start_time: this.binlogStartTime(),
          end_time: this.binlogEndTime(),
          page: this.binlogPage,
          page_size: this.binlogPageSize
        });
        this.binlogItems = data.items || [];
        this.binlogTotal = data.total || 0;
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.binlogLoading = false;
      }
    },
    routeParams() {
      return {
        accountId: Number(this.$route.query.account_id),
        region: this.$route.query.region || '',
        instanceId: this.$route.params.instanceId || ''
      };
    },
    binlogStartTime() {
      const end = new Date();
      const start = new Date(end.getTime() - this.binlogDays * 24 * 3600 * 1000);
      return this.formatCloudMinute(start);
    },
    binlogEndTime() {
      return this.formatCloudMinute(new Date());
    },
    formatCloudMinute(date) {
      const pad = (value) => String(value).padStart(2, '0');
      return (
        `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}` +
        `T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}Z`
      );
    },
    handleBackupPageChange(page) {
      this.backupPage = page;
      this.loadBackups();
    },
    handleBackupPageSizeChange(_page, pageSize) {
      this.backupPageSize = pageSize;
      this.backupPage = 1;
      this.loadBackups();
    },
    handleBinlogPageChange(page) {
      this.binlogPage = page;
      this.loadBinlog();
    },
    handleBinlogPageSizeChange(_page, pageSize) {
      this.binlogPageSize = pageSize;
      this.binlogPage = 1;
      this.loadBinlog();
    },
    handleBinlogDaysChange() {
      this.binlogPage = 1;
      this.loadBinlog();
    },
    async loadCrossBackups() {
      const { accountId, region, instanceId } = this.routeParams();
      if (!accountId || !region || !instanceId || this.crossBackupLoading) {
        return;
      }
      // 异地备份未开启时阿里云会直接报错，这里直接展示空列表
      if (!this.crossBackupEnabled) {
        this.crossBackupItems = [];
        this.crossBackupTotal = 0;
        return;
      }
      this.crossBackupLoading = true;
      try {
        const data = await listCrossRegionBackups(accountId, region, instanceId, {
          start_time: this.formatCloudSecond(this.crossStartTime(this.crossDays)),
          end_time: this.formatCloudSecond(new Date()),
          page: this.crossBackupPage,
          page_size: this.crossBackupPageSize
        });
        this.crossBackupItems = data.items || [];
        this.crossBackupTotal = data.total || 0;
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.crossBackupLoading = false;
      }
    },
    async loadCrossLogs() {
      const { accountId, region, instanceId } = this.routeParams();
      if (!accountId || !region || !instanceId || this.crossLogLoading) {
        return;
      }
      // 异地备份未开启时异地日志备份也查不到数据，直接展示空列表
      if (!this.crossBackupEnabled) {
        this.crossLogItems = [];
        this.crossLogTotal = 0;
        return;
      }
      this.crossLogLoading = true;
      try {
        const data = await listCrossRegionLogBackupFiles(accountId, region, instanceId, {
          start_time: this.formatCloudSecond(this.crossStartTime(this.crossLogDays)),
          end_time: this.formatCloudSecond(new Date()),
          page: this.crossLogPage,
          page_size: this.crossLogPageSize
        });
        this.crossLogItems = data.items || [];
        this.crossLogTotal = data.total || 0;
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.crossLogLoading = false;
      }
    },
    crossStartTime(days) {
      return new Date(Date.now() - days * 24 * 3600 * 1000);
    },
    formatCloudSecond(date) {
      // 跨地域接口的时间参数要求带秒：yyyy-MM-ddTHH:mm:ssZ
      const pad = (value) => String(value).padStart(2, '0');
      return (
        `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}` +
        `T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}Z`
      );
    },
    handleCrossBackupPageChange(page) {
      this.crossBackupPage = page;
      this.loadCrossBackups();
    },
    handleCrossBackupPageSizeChange(_page, pageSize) {
      this.crossBackupPageSize = pageSize;
      this.crossBackupPage = 1;
      this.loadCrossBackups();
    },
    handleCrossLogPageChange(page) {
      this.crossLogPage = page;
      this.loadCrossLogs();
    },
    handleCrossLogPageSizeChange(_page, pageSize) {
      this.crossLogPageSize = pageSize;
      this.crossLogPage = 1;
      this.loadCrossLogs();
    },
    handleCrossDaysChange() {
      this.crossBackupPage = 1;
      this.loadCrossBackups();
    },
    handleCrossLogDaysChange() {
      this.crossLogPage = 1;
      this.loadCrossLogs();
    },
    // ---- 备份恢复演练 ----
    isDrillActive(status) {
      return isDrillActive(status);
    },
    drillsByBackupId(backupId) {
      // 同一备份集的全部演练，新发起的排前
      return this.drills.filter((drill) => String(drill.backup_id) === String(backupId)).sort((a, b) => b.id - a.id);
    },
    drillBadgeTooltip(drill) {
      const status = this.drillStatusLabel(drill.status);
      if (isDrillActive(drill.status)) {
        return `${status} · ${this.$t('dian-ji-cha-kan-yan-lian-xiang-qing')}`;
      }
      return status;
    },
    async loadDrills() {
      const { accountId, region, instanceId } = this.routeParams();
      if (!accountId || !region || !instanceId) {
        return;
      }
      try {
        const data = await listBackupDrills({
          account_id: accountId,
          instance_id: instanceId,
          page: 1,
          page_size: 100
        });
        this.drills = data.items || [];
      } catch (error) {
        // 徽标刷新失败不弹错（下一次轮询会重试），只在终态缺失时影响展示
      }
      this.syncDrillPolling();
    },
    // 仅存在未终态演练时启动 10s 轮询；全部终态停表。
    syncDrillPolling() {
      const hasActive = this.drills.some((drill) => isDrillActive(drill.status));
      if (!hasActive) {
        this.stopDrillPolling();
        return;
      }
      if (this.drillPollTimer) {
        return;
      }
      this.drillPollTimer = setInterval(() => {
        if (!document.hidden) {
          this.loadDrills();
        }
      }, DRILL_POLL_INTERVAL_MS);
    },
    stopDrillPolling() {
      if (this.drillPollTimer) {
        clearInterval(this.drillPollTimer);
        this.drillPollTimer = null;
      }
    },
    openRestoreModal(backup) {
      const { accountId, region, instanceId } = this.routeParams();
      this.restoreContext = {
        accountId,
        region,
        instanceId,
        instanceName: (this.detail && this.detail.instance_name) || '',
        backup
      };
      this.restoreOpen = true;
    },
    handleDrillStarted() {
      this.loadDrills();
    },
    openDrillDetail(drill) {
      this.$router
        .push({
          path: `/dmops/drill/${drill.id}`,
          query: {
            from: 'instance',
            account_id: this.$route.query.account_id,
            region: this.$route.query.region
          }
        })
        .catch(() => {});
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-detail {
  gap: 12px;
  overflow: hidden;
}

.dmops-detail-bar {
  display: flex;
  align-items: center;
}

.dmops-detail-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding-left: 0;
}

// 返回栏与 Tab 头固定，只有 Tab 内容区滚动，避免下方信息被裁掉
.dmops-detail-tabs {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;

  :deep(.ant-tabs-nav) {
    flex-shrink: 0;
    margin-bottom: 12px;
  }

  :deep(.ant-tabs-content-holder) {
    flex: 1;
    min-height: 0;
    padding-right: 4px;
    overflow-y: auto;
  }
}

.dmops-descriptions {
  margin-bottom: 16px;

  &:last-child {
    margin-bottom: 0;
  }

  :deep(.ant-descriptions-item-label) {
    white-space: nowrap;
  }

  :deep(.ant-descriptions-item-content) {
    word-break: break-all;
  }
}

// 备份详情区：策略在上，列表在下
// 备份策略：三个横向卡片，各自内部纵向描述
.dmops-policy-hint {
  margin-bottom: 12px;
}

.dmops-policy-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;

  @media (max-width: 991px) {
    grid-template-columns: 1fr;
  }
}

// 备份策略卡片：白底 + 描边，标题条灰底，Descriptions 本身无边框
.dmops-policy-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 4px;

  &__title {
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-light);
    border-radius: 4px 4px 0 0;
  }

  &__body {
    flex: 1;
    padding: 8px 4px 4px 16px;

    :deep(.ant-descriptions-item-label) {
      white-space: nowrap;
    }

    :deep(.ant-descriptions-item-content) {
      word-break: break-all;
    }

    :deep(.ant-descriptions-item) {
      padding-bottom: 8px;
    }
  }
}

.dmops-backup {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dmops-backup-list {
  :deep(.ant-tabs-nav) {
    margin-bottom: 8px;
  }
}

.dmops-backup-table {
  :deep(.ant-table-cell) {
    vertical-align: middle;
  }
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

.dmops-muted {
  color: var(--text-tertiary);
}

// 备份模式徽标
.dmops-badge-auto,
.dmops-badge-manual {
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  font-size: 12px;
  line-height: 20px;
  border-radius: 2px;
}

.dmops-badge-auto {
  color: var(--text-secondary);
  background: var(--bg-secondary);
}

.dmops-badge-manual {
  color: var(--primary-color);
  background: rgba(22, 119, 255, 0.08);
}

.dmops-binlog-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;

  &__label {
    color: var(--text-secondary);
  }
}

.dmops-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

// 行内「备份恢复按钮 | 演练任务链接」组合单元：
// 左侧按钮垂直居中，右侧任务链接纵向每行一个；无任务时只占按钮宽度。
.dmops-restore-cell {
  display: flex;
  gap: 8px;
  align-items: center;

  &__action {
    flex-shrink: 0;
  }

  &__tasks {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding-left: 8px;
    border-left: 1px solid var(--border-light);
  }
}

.dmops-restore-task {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  overflow: hidden;
  color: var(--primary-color);
  white-space: nowrap;
  cursor: pointer;

  &.is-active {
    color: #1677ff;
  }
}
</style>
