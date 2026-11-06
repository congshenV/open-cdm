<template>
  <!-- 演练报告视图（五段结构，§7.1）：背景 / 基础信息 / 时间线 / 数据校验 / 结论 + 待办。 -->
  <div class="content-wrapper dmops-drill-detail">
    <div class="dmops-detail-bar">
      <a-button type="link" class="dmops-detail-back" @click="goBack">
        <CustomIcon type="icon-v2-ArrowLeftSimple" size="14px" />
        <span>{{ backLabel }}</span>
      </a-button>
      <a-button v-if="drill" size="small" class="dmops-drill-export" :loading="exporting" @click="handleExportMd">
        {{ $t('dao-chu-bao-gao') }}
      </a-button>
    </div>

    <a-spin :spinning="loading">
      <a-result v-if="loadError" status="error" :title="$t('yun-wei-jie-kou-diao-yong-shi-bai')" :sub-title="loadError">
        <template #extra>
          <a-button @click="loadDetail">{{ $t('shua-xin') }}</a-button>
        </template>
      </a-result>

      <template v-else-if="drill">
        <!-- 一、背景：固定审计文案 -->
        <div class="dmops-drill-section">
          <div class="dmops-drill-section__title">{{ $t('bao-gao-bei-jing') }}</div>
          <p class="dmops-drill-report__text">{{ $t('bao-gao-bei-jing-wen-an') }}</p>
        </div>

        <!-- 二、基础信息 -->
        <div class="dmops-drill-section">
          <div class="dmops-drill-section__title">{{ $t('bao-gao-ji-chu-xin-xi') }}</div>
          <a-descriptions size="small" :column="{ xs: 1, sm: 2, lg: 3 }" class="dmops-drill-report__desc">
            <a-descriptions-item :label="$t('yan-lian-bian-hao')">{{ text(drill.drill_no) }}</a-descriptions-item>
            <a-descriptions-item :label="$t('zhuang-tai')">
              <a-tag :color="drillStatusColor(drill.display_status)">{{ drillStatusLabel(drill.display_status) }}</a-tag>
            </a-descriptions-item>
            <a-descriptions-item :label="$t('fu-ze-ren')">{{ text(drill.triggered_by) }}</a-descriptions-item>
            <a-descriptions-item :label="$t('yuan-shi-li')" :span="2">
              {{ sourceInstanceText }}
            </a-descriptions-item>
            <a-descriptions-item :label="$t('di-qu')">{{ text(drill.region) }}</a-descriptions-item>
            <a-descriptions-item v-if="drill.clone_instance_id" :label="$t('hui-fu-shi-li')" :span="2">
              {{ cloneInstanceText }}
            </a-descriptions-item>
            <a-descriptions-item v-if="drill.clone_instance_id" :label="$t('gui-ge-kou-jing')">
              {{ cloneClassText }}
            </a-descriptions-item>
            <a-descriptions-item :label="$t('suo-yong-bei-fen-ji')" :span="2">
              {{ backupText }}
            </a-descriptions-item>
            <a-descriptions-item :label="$t('zhi-xing-shi-jian')">{{ execTimeText }}</a-descriptions-item>
          </a-descriptions>
        </div>

        <!-- 三、操作时间线 -->
        <div class="dmops-drill-section">
          <div class="dmops-drill-section__title">{{ $t('bao-gao-cao-zuo-shi-jian-xian') }}</div>
          <table class="dmops-drill-timeline-table">
            <thead>
              <tr>
                <th>{{ $t('bao-gao-jie-duan') }}</th>
                <th>{{ $t('bao-gao-kai-shi') }}</th>
                <th>{{ $t('bao-gao-jie-shu') }}</th>
                <th>{{ $t('bao-gao-hao-shi') }}</th>
                <th>{{ $t('bao-gao-bei-zhu') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{{ $t('bao-gao-jie-duan-bei-fen-hui-fu') }}</td>
                <td>{{ text(drill.clone_started_at) }}</td>
                <td>{{ text(drill.clone_finished_at) }}</td>
                <td>{{ stageMinutes(drill.clone_started_at, drill.clone_finished_at) }}</td>
                <td class="dmops-drill-timeline-table__note">{{ cloneStageNote }}</td>
              </tr>
              <tr>
                <td>{{ $t('bao-gao-jie-duan-shu-ju-jiao-yan') }}</td>
                <td>{{ text(verifyStage.start) }}</td>
                <td>{{ text(verifyStage.end) }}</td>
                <td>{{ verifyStage.duration }}</td>
                <td class="dmops-drill-timeline-table__note">{{ verifyStage.note }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 数据源注册：数据校验的前置（源端/克隆实例分别注册，成功后回填 dsId） -->
        <div v-if="drill.status === 'success' && drill.offline_status === 0" class="dmops-drill-section">
          <div class="dmops-drill-section__title">{{ $t('shu-ju-yuan-zhu-ce') }}</div>
          <div class="dmops-drill-register">
            <div class="dmops-drill-register__row">
              <span class="dmops-drill-register__label">{{ $t('yuan-duan-shi-li') }}</span>
              <template v-if="drill.source_ds_id">
                <a-tag color="green">{{ $t('yi-zhu-ce-ds', { dsId: drill.source_ds_id }) }}</a-tag>
              </template>
              <a-button v-else size="small" @click="openRegister('source')">
                {{ $t('zhu-ce-yuan-duan-shu-ju-yuan') }}
              </a-button>
            </div>
            <div class="dmops-drill-register__row">
              <span class="dmops-drill-register__label">{{ $t('ke-long-duan-shi-li') }}</span>
              <template v-if="drill.clone_ds_id">
                <a-tag color="green">{{ $t('yi-zhu-ce-ds', { dsId: drill.clone_ds_id }) }}</a-tag>
              </template>
              <a-button v-else size="small" @click="openRegister('clone')">
                {{ $t('zhu-ce-ke-long-shu-ju-yuan') }}
              </a-button>
            </div>
            <div class="dmops-drill-register__hint">{{ $t('shu-ju-yuan-zhu-ce-ti-shi') }}</div>
          </div>
        </div>

        <!-- 四、数据校验结果：手动触发，历史追加 -->
        <div class="dmops-drill-section">
          <div class="dmops-drill-section__title">{{ $t('bao-gao-shu-ju-jiao-yan-jie-guo') }}</div>

          <!-- 操作条：两类校验按需触发 -->
          <div v-if="drill.status === 'success' && drill.offline_status === 0" class="dmops-drill-verify__actions">
            <a-button size="small" :loading="verifying" @click="handleVerifyDbTables">
              {{ $t('ku-biao-shu-liang-jiao-yan') }}
            </a-button>
            <a-button size="small" @click="tablePickerOpen = true">
              {{ $t('biao-shu-ju-jiao-yan') }}
            </a-button>
            <span class="dmops-field-hint">{{ $t('jiao-yan-cha-yi-bu-pan-ding-ti-shi') }}</span>
          </div>

          <!-- 校验结果：只展示最近一次（AUTO 最近一条 + ROW 最近一批，各一卡片） -->
          <div v-if="latestAuto || latestRowBatch" class="dmops-drill-verify">
            <!-- AUTO：库表数量对比 -->
            <div v-if="latestAuto" class="dmops-drill-verify__item">
              <div class="dmops-drill-verify__head">
                <a-tag v-if="latestAuto.status === 'pass'" color="green">{{ $t('jiao-yan-yi-zhi') }}</a-tag>
                <a-tag v-else color="orange">{{ $t('jiao-yan-cun-zai-cha-yi') }}</a-tag>
                <span class="dmops-drill-verify__meta">
                  {{ `${latestAuto.created_at} · ${$t('hao-shi-ti-shi')} ${Math.max(1, Math.round((latestAuto.cost_ms || 0) / 1000))}s` }}
                </span>
              </div>
              <div class="dmops-drill-verify__summary">
                {{
                  `${$t('yuan-duan-ku-shu')} ${latestAuto.summary.source_dbs ?? '-'} · ${$t('ke-long-duan-ku-shu')} ${latestAuto.summary.clone_dbs ?? '-'} · ${$t('cha-yi-shu')} ${latestAuto.summary.diff_count ?? 0}`
                }}
              </div>
              <div v-if="latestAuto.error" class="dmops-drill-verify__error">{{ latestAuto.error }}</div>
              <!-- 两侧库清单 -->
              <div v-if="latestAuto.source_dbs.length || latestAuto.clone_dbs.length" class="dmops-drill-dblist">
                <div class="dmops-drill-dblist__col">
                  <div class="dmops-drill-dblist__title">{{ $t('yuan-duan-ku-lie-biao') }}（{{ latestAuto.source_dbs.length }}）</div>
                  <div
                    v-for="db in latestAuto.source_dbs"
                    :key="`s-${db.db}`"
                    class="dmops-drill-dblist__item"
                    :class="{ 'is-diff': isDiffDb(latestAuto, db.db) }"
                  >
                    <span class="dmops-drill-dblist__name">{{ db.db }}</span>
                    <span class="dmops-drill-dblist__count">{{ `${db.tables} ${$t('zhang-biao')}` }}</span>
                  </div>
                  <div v-if="!latestAuto.source_dbs.length" class="dmops-field-hint">-</div>
                </div>
                <div class="dmops-drill-dblist__col">
                  <div class="dmops-drill-dblist__title">{{ $t('ke-long-duan-ku-lie-biao') }}（{{ latestAuto.clone_dbs.length }}）</div>
                  <div
                    v-for="db in latestAuto.clone_dbs"
                    :key="`c-${db.db}`"
                    class="dmops-drill-dblist__item"
                    :class="{ 'is-diff': isDiffDb(latestAuto, db.db) }"
                  >
                    <span class="dmops-drill-dblist__name">{{ db.db }}</span>
                    <span class="dmops-drill-dblist__count">{{ `${db.tables} ${$t('zhang-biao')}` }}</span>
                  </div>
                  <div v-if="!latestAuto.clone_dbs.length" class="dmops-field-hint">-</div>
                </div>
              </div>
              <table v-if="latestAuto.diffs.length" class="dmops-drill-diff-table">
                <thead>
                  <tr>
                    <th>{{ $t('dui-xiang') }}</th>
                    <th>{{ $t('cha-yi-lei-xing') }}</th>
                    <th>{{ $t('yuan-duan-zhi') }}</th>
                    <th>{{ $t('ke-long-duan-zhi') }}</th>
                    <th>{{ $t('shuo-ming') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="diff in latestAuto.diffs" :key="diff.id">
                    <td class="dmops-drill-diff-table__mono">{{ diff.target }}</td>
                    <td>{{ diffTypeLabel(diff.item_type) }}</td>
                    <td class="dmops-drill-diff-table__mono">{{ diff.source_value || '-' }}</td>
                    <td class="dmops-drill-diff-table__mono">{{ diff.clone_value || '-' }}</td>
                    <td class="dmops-drill-diff-table__note">{{ diff.note }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- ROW：表数据对比（最近一批，多表一卡） -->
            <div v-if="latestRowBatch" class="dmops-drill-verify__item">
              <div class="dmops-drill-verify__head">
                <a-tag v-if="latestRowBatch.status === 'pass'" color="green">{{ $t('jiao-yan-yi-zhi') }}</a-tag>
                <a-tag v-else-if="latestRowBatch.status === 'skip'" color="default">{{ $t('yi-tiao-guo') }}</a-tag>
                <a-tag v-else color="orange">{{ $t('jiao-yan-cun-zai-cha-yi') }}</a-tag>
                <a-tag color="blue" class="dmops-tpicker__mark">{{ $t('biao-shu-ju') }}</a-tag>
                <span class="dmops-drill-verify__meta">
                  {{ `${latestRowBatch.created_at} · ${$t('hao-shi-ti-shi')} ${Math.max(1, Math.round((latestRowBatch.total_ms || 0) / 1000))}s` }}
                </span>
              </div>
              <div class="dmops-drill-verify__summary">
                {{ `${latestRowSummary.passed}/${latestRowSummary.total} ${$t('biao-tong-guo')}` }}
              </div>
              <table class="dmops-drill-diff-table">
                <tbody>
                  <tr v-for="row in latestRowTables" :key="row.table">
                    <td class="dmops-drill-batch__status">
                      <span :class="rowStatusClass(row.status)">{{ rowStatusMark(row.status) }}</span>
                    </td>
                    <td class="dmops-drill-diff-table__mono dmops-drill-batch__name">{{ row.table }}</td>
                    <td class="dmops-drill-diff-table__note">{{ row.note }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-else class="dmops-drill-verify__empty">{{ $t('zan-wei-zhi-xing-jiao-yan') }}</div>
        </div>

        <!-- 五、测试结论 -->
        <div class="dmops-drill-section">
          <div class="dmops-drill-section__title">{{ $t('bao-gao-ce-shi-jie-lun') }}</div>
          <p class="dmops-drill-report__text">{{ conclusionText }}</p>
        </div>

        <!-- 待办提醒：仅未确认下线时展示 -->
        <div v-if="drill.clone_instance_id && drill.offline_status === 0" class="dmops-drill-section">
          <div class="dmops-drill-section__title">{{ $t('dai-xia-xian-qing-dan') }}</div>
          <div class="dmops-drill-offline">
            <div class="dmops-drill-offline__row">
              <span class="dmops-drill-offline__label">{{ $t('ke-long-shi-li') }}</span>
              <span class="dmops-drill-offline__value">{{ cloneInstanceText }}</span>
            </div>
            <div class="dmops-drill-offline__row">
              <span class="dmops-drill-offline__label">{{ $t('xia-xian-zhuang-tai') }}</span>
              <span>{{ $t('dai-xia-xian') }}</span>
            </div>
            <div class="dmops-drill-offline__row">
              <span class="dmops-drill-offline__label">{{ $t('cao-zuo') }}</span>
              <a-popconfirm :title="$t('que-ren-xia-xian-ti-shi')" @confirm="handleConfirmOffline">
                <a-button size="small" :loading="confirming">{{ $t('que-ren-xia-xian') }}</a-button>
              </a-popconfirm>
            </div>
            <a-alert class="dmops-drill-offline__hint" type="warning" show-icon :message="$t('ke-long-shi-li-ji-fei-ti-shi')" />
          </div>
        </div>

        <!-- 已确认下线：一行轻量记录（不打扰主报告） -->
        <div v-else-if="drill.clone_instance_id && drill.offline_status === 1" class="dmops-drill-offline-done">
          {{ `${$t('yi-que-ren-xia-xian')}${offlineConfirmedText} · ${cloneInstanceText}` }}
        </div>
      </template>
    </a-spin>

    <!-- 注册数据源弹窗（源端/克隆实例） -->
    <RegisterDsModal v-model:open="registerOpen" :context="registerContext" @registered="loadDetail" />
    <TablePickerModal v-model:open="tablePickerOpen" :drill-id="drill ? drill.id : 0" @done="loadAfterVerify" />
  </div>
</template>

<script>
import Toast from '@/utils/toast';
import { confirmDrillOffline, getBackupDrill, listVerifications, verifyDbTables } from '@/services/http/dmops';
import { drillLabels, isDrillActive } from '@/views/dmops/utils/drill';
import RegisterDsModal from '@/views/dmops/components/RegisterDsModal';
import TablePickerModal from '@/views/dmops/components/TablePickerModal';

// 未终态时的详情刷新间隔，与备份集列表行内徽标口径一致。
const REFRESH_INTERVAL_MS = 10000;

export default {
  name: 'DmOpsDrillDetail',
  components: { RegisterDsModal, TablePickerModal },
  mixins: [drillLabels],
  data() {
    return {
      loading: false,
      loadError: '',
      drill: null,
      confirming: false,
      exporting: false,
      registerOpen: false,
      registerContext: null,
      tablePickerOpen: false,
      verifying: false,
      verifications: [],
      refreshTimer: null
    };
  },
  computed: {
    // 只展示最近一次：AUTO 最近一条 + ROW 最近一批（历史不展示）。
    latestAuto() {
      return this.verifications.find((item) => item.layer === 'AUTO') || null;
    },
    latestRowBatch() {
      return this.verifications.find((item) => item.layer === 'ROW-BATCH') || null;
    },
    // 一次触发的多表（新数据在同一 ROW-BATCH 内；老数据退化为多条单表批次，
    // 取首批往前时间相邻（≤10s）的批次合并成一张卡）。
    latestRowTables() {
      if (!this.latestRowBatch) {
        return [];
      }
      const firstAt = new Date(this.latestRowBatch.created_at.replace(/-/g, '/')).getTime();
      const tables = [...(this.latestRowBatch.tables || [])];
      for (const item of this.verifications) {
        if (item === this.latestRowBatch || item.layer !== 'ROW-BATCH') {
          continue;
        }
        const at = new Date(item.created_at.replace(/-/g, '/')).getTime();
        if (at >= firstAt && at - firstAt <= 10000) {
          tables.push(...(item.tables || []));
        } else {
          break;
        }
      }
      return tables;
    },
    latestRowSummary() {
      const total = this.latestRowTables.length;
      const passed = this.latestRowTables.filter((row) => row.status === 'pass').length;
      return { total, passed };
    },
    sourceInstanceText() {
      if (!this.drill) {
        return '-';
      }
      const name = this.drill.source_instance_name;
      const engine = this.drill.source_engine;
      let text_value = this.drill.source_instance_id || '-';
      if (name) {
        text_value += ` | ${name}`;
      }
      if (engine) {
        text_value += ` · ${engine}`;
      }
      return text_value;
    },
    cloneInstanceText() {
      if (!this.drill || !this.drill.clone_instance_id) {
        return '-';
      }
      const name = this.drill.clone_instance_name;
      if (name) {
        return `${this.drill.clone_instance_id} | ${name}`;
      }
      return this.drill.clone_instance_id;
    },
    cloneClassText() {
      if (!this.drill) {
        return '-';
      }
      const parts = [this.drill.clone_pay_type, this.drill.clone_class_desc].filter(Boolean);
      return parts.length ? parts.join(' · ') : '-';
    },
    backupText() {
      if (!this.drill) {
        return '-';
      }
      const parts = [this.drill.backup_id];
      if (this.drill.backup_type) {
        parts.push(this.drill.backup_type);
      }
      if (this.drill.backup_end_time) {
        parts.push(`${this.$t('bei-fen-wan-cheng')} ${this.drill.backup_end_time}`);
      }
      return parts.join(' · ');
    },
    execTimeText() {
      if (!this.drill) {
        return '-';
      }
      const start = this.drill.created_at;
      const end = this.drill.finished_at;
      if (!start || !end) {
        return start || '-';
      }
      const minutes = this.drill.total_minutes;
      if (minutes === null || minutes === undefined) {
        return `${start} ~ ${end}`;
      }
      return `${start} ~ ${end}（${this.$t('bao-gao-zong-hao-shi', { minutes })}）`;
    },
    cloneStageNote() {
      if (!this.drill) {
        return '';
      }
      if (this.drill.status === 'failed' && this.drill.error_message) {
        return this.drill.error_message;
      }
      return '';
    },
    // 时间线"数据校验"行：手动触发的最近一次校验（AUTO/ROW 取更晚者作阶段终点）。
    verifyStage() {
      const rows = [];
      if (this.latestAuto) {
        rows.push({ at: this.latestAuto.created_at, ms: this.latestAuto.cost_ms || 0, label: this.$t('ku-biao-shu-liang-jiao-yan') });
      }
      if (this.latestRowBatch) {
        rows.push({ at: this.latestRowBatch.created_at, ms: this.latestRowBatch.total_ms || 0, label: this.$t('biao-shu-ju') });
      }
      if (!rows.length) {
        return { start: '', end: '', duration: '-', note: this.$t('wei-zhi-xing') };
      }
      const toTime = (value) => new Date(String(value).replace(/-/g, '/')).getTime();
      const latest = rows.reduce((a, b) => (toTime(b.at) > toTime(a.at) ? b : a));
      const startMs = toTime(latest.at);
      const endMs = startMs + latest.ms;
      const fmt = (ms) => {
        const date = new Date(ms);
        const pad = (n) => String(n).padStart(2, '0');
        return (
          `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
          ` ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
        );
      };
      const labels = rows.map((row) => row.label).join(' + ');
      return {
        start: fmt(startMs),
        end: fmt(endMs),
        duration: this.$t('bao-gao-fen-zhong', { minutes: Math.max(1, Math.round(latest.ms / 1000 / 60)) }),
        note: `${labels}（手动触发）`
      };
    },
    // success 结论按校验档位拼接：全通过 / 有差异 / 未校验（其他状态不变）。
    conclusionVerifySuffix() {
      const auto = this.latestAuto;
      const row = this.latestRowTables;
      const hasRow = this.latestRowBatch && row.length > 0;
      if (!auto && !hasRow) {
        return this.$t('bao-gao-jie-lun-verify-none');
      }
      const autoOk = !auto || auto.status === 'pass';
      const rowOk = !hasRow || row.every((item) => item.status === 'pass');
      if (autoOk && rowOk) {
        return this.$t('bao-gao-jie-lun-verify-all-pass');
      }
      return this.$t('bao-gao-jie-lun-verify-diff');
    },
    conclusionText() {
      if (!this.drill) {
        return '';
      }
      if (this.drill.status === 'success') {
        return this.$t('bao-gao-jie-lun-success', { verify: this.conclusionVerifySuffix });
      }
      if (this.drill.status === 'failed') {
        return this.$t('bao-gao-jie-lun-failed', { reason: this.drill.error_message || '-' });
      }
      if (this.drill.status === 'canceled') {
        return this.$t('bao-gao-jie-lun-canceled');
      }
      return this.$t('bao-gao-jie-lun-running');
    },
    offlineConfirmedText() {
      const by = this.drill && this.drill.offline_confirmed_by;
      return by ? `（${by}）` : '';
    },
    backLabel() {
      // 从实例详情进入则回到实例详情，否则回历史列表。
      if (this.$route.query.from === 'instance') {
        return this.$t('fan-hui-shi-li-xiang-qing');
      }
      return this.$t('fan-hui-yan-lian-lie-biao');
    }
  },
  watch: {
    '$route.params.drillId'() {
      this.loadDetail();
    }
  },
  mounted() {
    this.loadDetail();
  },
  beforeUnmount() {
    this.stopRefresh();
  },
  methods: {
    text(value) {
      return value === null || value === undefined || value === '' ? '-' : String(value);
    },
    stageMinutes(start, end) {
      if (!start || !end) {
        return '-';
      }
      const seconds = (new Date(end.replace(/-/g, '/')) - new Date(start.replace(/-/g, '/'))) / 1000;
      if (!Number.isFinite(seconds) || seconds < 0) {
        return '-';
      }
      return this.$t('bao-gao-fen-zhong', { minutes: Math.max(1, Math.round(seconds / 60)) });
    },
    goBack() {
      if (this.$route.query.from === 'instance') {
        this.$router
          .push({
            path: `/dmops/instance/${encodeURIComponent(this.drill ? this.drill.source_instance_id : '')}`,
            query: {
              account_id: this.$route.query.account_id,
              region: this.$route.query.region
            }
          })
          .catch(() => {});
        return;
      }
      this.$router.push('/dmops/drill').catch(() => {});
    },
    async loadDetail() {
      const drillId = Number(this.$route.params.drillId);
      if (!drillId) {
        this.drill = null;
        this.loadError = this.$t('shi-li-can-shu-bu-wan-zheng');
        return;
      }
      this.loading = true;
      this.loadError = '';
      try {
        this.drill = await getBackupDrill(drillId);
        this.syncRefresh();
        this.loadVerifications();
      } catch (error) {
        this.drill = null;
        this.loadError = error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai');
        this.stopRefresh();
      } finally {
        this.loading = false;
      }
    },
    // ---- 数据校验 ----
    diffTypeLabel(type) {
      const labels = {
        db_missing: this.$t('ke-long-ce-que-shi'),
        db_extra: this.$t('yuan-ce-que-shi'),
        db_table_count: this.$t('biao-shu-liang-bu-deng'),
        row_attempt: this.$t('xing-ji-dui-bi')
      };
      return labels[type] || type;
    },
    isDiffDb(item, dbName) {
      return (item.diffs || []).some((diff) => diff.target === dbName);
    },
    // 批次内表状态符与配色（✓/−/✗ 为 i18n 例外符号，方法返回不触发裸文本检查）。
    rowStatusMark(status) {
      if (status === 'pass') {
        return '✓';
      }
      if (status === 'skip') {
        return '−';
      }
      return '✗';
    },
    rowStatusClass(status) {
      if (status === 'pass') {
        return 'dmops-drill-batch__ok';
      }
      if (status === 'skip') {
        return 'dmops-drill-batch__skip';
      }
      return 'dmops-drill-batch__bad';
    },
    async loadVerifications() {
      const drillId = Number(this.$route.params.drillId);
      if (!drillId) {
        return;
      }
      try {
        const data = await listVerifications(drillId);
        this.verifications = data.items || [];
      } catch (error) {
        // 历史加载失败不阻塞详情展示
        this.verifications = [];
      }
    },
    async handleVerifyDbTables() {
      if (!this.drill || this.verifying) {
        return;
      }
      this.verifying = true;
      try {
        const data = await verifyDbTables(this.drill.id);
        if (data.diff_count === 0) {
          Toast.success(this.$t('jiao-yan-yi-zhi'));
        } else {
          Toast.warning(this.$t('jiao-yan-fa-xian-cha-yi', { count: data.diff_count }));
        }
        await this.loadVerifications();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.verifying = false;
      }
    },
    async loadAfterVerify() {
      await this.loadVerifications();
    },
    // 未终态 10s 轮询刷新；终态停表。
    syncRefresh() {
      this.stopRefresh();
      if (!this.drill || !isDrillActive(this.drill.status)) {
        return;
      }
      this.refreshTimer = setInterval(() => {
        if (!document.hidden) {
          this.loadDetail();
        }
      }, REFRESH_INTERVAL_MS);
    },
    stopRefresh() {
      if (this.refreshTimer) {
        clearInterval(this.refreshTimer);
        this.refreshTimer = null;
      }
    },
    openRegister(target) {
      if (!this.drill) {
        return;
      }
      this.registerContext = { drillId: this.drill.id, target };
      this.registerOpen = true;
    },
    async handleConfirmOffline() {
      if (!this.drill || this.confirming) {
        return;
      }
      this.confirming = true;
      try {
        await confirmDrillOffline(this.drill.id);
        Toast.success(this.$t('cao-zuo-cheng-gong'));
        await this.loadDetail();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.confirming = false;
      }
    },
    // ---- 导出 md 报告 ----
    handleExportMd() {
      if (!this.drill || this.exporting) {
        return;
      }
      this.exporting = true;
      try {
        const content = this.buildReportMd();
        const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `drill-${this.drill.drill_no}.md`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.exporting = false;
      }
    },
    // 报告 md 渲染（§7.2 纯字符串拼接），与页面五段结构一致。
    buildReportMd() {
      const drill = this.drill;
      const t = this.$t.bind(this);
      const lines = [];

      lines.push(`# ${t('bei-fen-hui-fu-yan-lian')} ${drill.drill_no}`, '');
      lines.push(t('bao-gao-bei-jing-wen-an'), '');
      lines.push('---', '');

      lines.push(`## ${t('bao-gao-ji-chu-xin-xi')}`, '');
      lines.push('| 项 | 值 |');
      lines.push('|---|---|');
      lines.push(`| ${t('yan-lian-bian-hao')} | ${drill.drill_no} |`);
      lines.push(`| ${t('zhuang-tai')} | ${this.drillStatusLabel(drill.display_status)} |`);
      lines.push(`| ${t('fu-ze-ren')} | ${this.text(drill.triggered_by)} |`);
      lines.push(`| ${t('yuan-shi-li')} | ${this.sourceInstanceText} |`);
      lines.push(`| ${t('di-qu')} | ${this.text(drill.region)} |`);
      if (drill.clone_instance_id) {
        lines.push(`| ${t('hui-fu-shi-li')} | ${this.cloneInstanceText} |`);
        lines.push(`| ${t('gui-ge-kou-jing')} | ${this.cloneClassText} |`);
      }
      lines.push(`| ${t('suo-yong-bei-fen-ji')} | ${this.backupText} |`);
      lines.push(`| ${t('zhi-xing-shi-jian')} | ${this.execTimeText} |`);
      lines.push('');

      lines.push(`## ${t('bao-gao-cao-zuo-shi-jian-xian')}`, '');
      lines.push(
        `| ${t('bao-gao-jie-duan')} | ${t('bao-gao-kai-shi')} | ${t('bao-gao-jie-shu')} | ${t('bao-gao-hao-shi')} | ${t('bao-gao-bei-zhu')} |`
      );
      lines.push('|---|---|---|---|---|');
      lines.push(
        `| ${t('bao-gao-jie-duan-bei-fen-hui-fu')} | ${this.text(drill.clone_started_at)} | ${this.text(drill.clone_finished_at)} | ${this.stageMinutes(drill.clone_started_at, drill.clone_finished_at)} | ${this.cloneStageNote || '-'} |`
      );
      lines.push(
        `| ${t('bao-gao-jie-duan-shu-ju-jiao-yan')} | ${this.verifyStage.start || '-'} | ${this.verifyStage.end || '-'} | ${this.verifyStage.duration} | ${this.verifyStage.note} |`
      );
      lines.push('');

      lines.push(`## ${t('bao-gao-shu-ju-jiao-yan-jie-guo')}`, '');
      this.pushVerificationMd(lines);
      lines.push(`## ${t('bao-gao-ce-shi-jie-lun')}`, '');
      lines.push(this.conclusionText, '');
      // 待下线清单只在页面上展示，不进导出报告（报告止于测试结论）。
      return lines.join('\n');
    },
    // 报告第四节：最近一次校验结果（AUTO/ROW 两种格式各自渲染）。
    pushVerificationMd(lines) {
      // 与页面一致：只导出最近一次（AUTO 最近一条 + ROW 最近一批）。
      if (!this.latestAuto && !this.latestRowBatch) {
        lines.push(`> ${this.$t('zhan-wei-zhi-xing-jiao-yan')}`, '');
        return;
      }
      const t = this.$t.bind(this);
      const statusTextOf = (status) =>
        status === 'pass' ? t('jiao-yan-yi-zhi') : status === 'skip' ? t('yi-tiao-guo') : t('jiao-yan-cun-zai-cha-yi');

      if (this.latestAuto) {
        const summary = this.latestAuto.summary || {};
        lines.push(
          `- ${t('ku-biao-shu-liang-jiao-yan')}：${statusTextOf(this.latestAuto.status)} · ${t('yuan-duan-ku-shu')} ${summary.source_dbs ?? '-'} · ` +
            `${t('ke-long-duan-ku-shu')} ${summary.clone_dbs ?? '-'} · ${t('cha-yi-shu')} ${summary.diff_count ?? 0}（${this.latestAuto.created_at}）`
        );
        (this.latestAuto.diffs || []).forEach((diff) => {
          lines.push(
            `  - ${diff.target} | ${this.diffTypeLabel(diff.item_type)} | ${diff.source_value || '-'} → ${diff.clone_value || '-'} | ${diff.note || ''}`
          );
        });
      }
      if (this.latestRowBatch) {
        lines.push(
          `- ${t('biao-shu-ju')}：${this.latestRowBatch.passed}/${this.latestRowBatch.total} ${t('biao-tong-guo')}（${this.latestRowBatch.created_at}）`
        );
        (this.latestRowBatch.tables || []).forEach((row) => {
          const mark = this.rowStatusMark(row.status);
          lines.push(`  - ${mark} ${row.table}：${row.note}`);
        });
      }
      lines.push('');
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-drill-detail {
  gap: 12px;
  overflow: hidden;
}

.dmops-detail-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}

// 导出按钮靠右，与返回键拉开层级（返回是导航、导出是本页操作）
.dmops-drill-export {
  margin-left: auto;
}

.dmops-detail-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding-left: 0;
}

// 只有描述列表之后的区域滚动
.dmops-drill-detail > :deep(.ant-spin-nested-loading) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.dmops-drill-section {
  margin-bottom: 16px;

  &__title {
    margin-bottom: 12px;
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
  }
}

// 报告正文段落
.dmops-drill-report__text {
  margin: 0;
  font-size: 14px;
  line-height: 22px;
  color: var(--text-primary);
}

.dmops-drill-report__desc {
  :deep(.ant-descriptions-item-label) {
    white-space: nowrap;
  }

  :deep(.ant-descriptions-item-content) {
    word-break: break-all;
  }
}

// 时间线表格：报告口径（阶段/开始/结束/耗时/备注），复用表格的发丝线风格
.dmops-drill-timeline-table {
  width: 100%;
  font-size: 13px;

  th,
  td {
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border-light);
  }

  th {
    font-weight: 500;
    color: var(--text-secondary);
    background: var(--bg-secondary);
  }

  td {
    color: var(--text-primary);

    &:first-child {
      white-space: nowrap;
    }
  }

  &__note {
    color: var(--text-tertiary);
    word-break: break-all;
  }
}

// 数据源注册区：浅底行式（源端/克隆端各一行），与待下线清单同风格
.dmops-drill-register {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  background: var(--bg-secondary);
  border-radius: 4px;

  &__row {
    display: flex;
    gap: 12px;
    align-items: center;
  }

  &__label {
    width: 72px;
    flex-shrink: 0;
    color: var(--text-secondary);
  }

  &__hint {
    font-size: 12px;
    line-height: 18px;
    color: var(--text-tertiary);
  }
}

// 数据校验区：操作条 + 历史条目（浅底，与待下线清单同风格）
.dmops-drill-verify {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-secondary);
  border-radius: 4px;

  &__actions {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 4px;
  }

  &__item {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border-light);

    &:last-child {
      padding-bottom: 0;
      border-bottom: none;
    }
  }

  &__head {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  &__meta {
    font-size: 12px;
    color: var(--text-tertiary);
  }

  &__summary {
    font-size: 13px;
    color: var(--text-primary);
  }

  &__error {
    font-size: 13px;
    color: #cf1322;
    word-break: break-all;
  }

  &__empty {
    font-size: 13px;
    color: var(--text-tertiary);
  }
}

// 两侧库清单：双列并列（源端 | 克隆端），命中差异的库红字标记
.dmops-drill-dblist {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;

  @media (max-width: 767px) {
    grid-template-columns: 1fr;
  }

  &__col {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    max-height: 320px;
    overflow-y: auto;
  }

  &__title {
    margin-bottom: 4px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
  }

  &__item {
    display: flex;
    gap: 8px;
    align-items: baseline;
    justify-content: space-between;
    padding: 2px 6px;
    font-size: 12px;
    border-radius: 2px;

    &.is-diff {
      color: #d4380d;
      background: rgba(212, 56, 13, 0.06);
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
}

// ROW 批次汇总表：状态符 + 表名 + 说明（复用 dmops-drill-diff-table 骨架）
.dmops-drill-batch {
  &__status {
    width: 28px;
    text-align: center;
  }

  &__ok {
    color: #52c41a;
  }

  &__skip {
    color: var(--text-tertiary);
  }

  &__bad {
    color: #ff4d4f;
  }

  &__name {
    white-space: nowrap;
  }
}

// diff 明细表（与时间线表同风格）
.dmops-drill-diff-table {
  width: 100%;
  font-size: 12px;

  th,
  td {
    padding: 6px 10px;
    text-align: left;
    border-bottom: 1px solid var(--border-light);
  }

  th {
    font-weight: 500;
    color: var(--text-secondary);
  }

  &__mono {
    font-family: Menlo, Monaco, 'Courier New', monospace;
    word-break: break-all;
  }

  &__note {
    color: var(--text-tertiary);
  }
}

// 待下线清单：浅底行式布局，与 page-aside 同类
.dmops-drill-offline {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  background: var(--bg-secondary);
  border-radius: 4px;

  &__row {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  &__label {
    width: 72px;
    flex-shrink: 0;
    color: var(--text-secondary);
  }

  &__value {
    font-family: Menlo, Monaco, 'Courier New', monospace;
    word-break: break-all;
  }

  &__hint {
    margin-top: 4px;
  }
}

// 已确认下线的轻量一行
.dmops-drill-offline-done {
  font-size: 13px;
  color: var(--text-tertiary);
  word-break: break-all;
}

.dmops-muted {
  color: var(--text-tertiary);
}
</style>
