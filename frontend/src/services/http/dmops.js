import axios from 'axios';
import i18n from '@/i18n';

/**
 * Dedicated axios instance for the dmops service.
 *
 * All requests go to /api/dmops/** on the same origin and are forwarded to the dmops
 * service by CloudDM console, so the frontend never needs to know the real dmops address.
 *
 * This instance deliberately does not reuse the global request interceptor: dmops keeps its
 * own response envelope and must not trigger CloudDM's global error modal.
 */
const dmops = axios.create({
  baseURL: '/api/dmops',
  timeout: 60000,
  withCredentials: true
});

dmops.interceptors.request.use((config) => {
  config.headers = config.headers || {};
  config.headers['Accept-Language'] = i18n.global.locale.value;
  return config;
});

// dmops 统一响应体：{ success, code, userMessage, message, data, ctx }
// 成功时直接返回 data，失败时抛出带 userMessage 的 Error，页面只需 try/catch。
dmops.interceptors.response.use(
  (response) => {
    const body = response.data || {};
    if (body.success === false) {
      return Promise.reject(new Error(body.userMessage || body.message || ''));
    }
    return body.data;
  },
  (error) => {
    const body = error.response && error.response.data;
    const message = (body && (body.userMessage || body.message)) || error.message;
    return Promise.reject(new Error(message));
  }
);

// ---- 阿里云账号 ----

export const listAccounts = (params) => dmops.get('/v1/cloud/accounts', { params });

export const createAccount = (data) => dmops.post('/v1/cloud/accounts', data);

export const updateAccount = (accountId, data) => dmops.put(`/v1/cloud/accounts/${accountId}`, data);

export const deleteAccount = (accountId) => dmops.delete(`/v1/cloud/accounts/${accountId}`);

export const syncAccount = (accountId) => dmops.post(`/v1/cloud/accounts/${accountId}/sync`, null, { timeout: 180000 });

// 账号下已同步资源涉及的地域，用于实例列表的地域筛选。
export const listAccountRegions = (accountId) => dmops.get(`/v1/cloud/accounts/${accountId}/regions`);

// ---- 云上实例 ----

// 实例列表读的是同步落库的 ops_resource，不会实时调用阿里云。
export const listInstances = (params) => dmops.get('/v1/instances', { params });

// 实例详情实时调用阿里云 DescribeDBInstanceAttribute，并回写资源快照。
export const getInstanceDetail = (accountId, region, instanceId) =>
  dmops.get(`/v1/instances/${encodeURIComponent(instanceId)}`, {
    params: { account_id: accountId, region }
  });

// 磁盘水位需要逐台查实例详情，只传当前页的实例。
export const getInstanceDiskUsage = (accountId, items) =>
  dmops.get('/v1/instances/disk-usage', {
    params: {
      account_id: accountId,
      items: items.map((item) => `${item.region}:${item.instance_id}`).join(',')
    }
  });

// ---- 备份详情 ----

// 备份策略实时调用 DescribeBackupPolicy。
export const getBackupPolicy = (accountId, region, instanceId) =>
  dmops.get(`/v1/instances/${encodeURIComponent(instanceId)}/backup-policy`, {
    params: { account_id: accountId, region }
  });

// 备份集列表实时调用 DescribeBackups，分页由后端透传（30/50/100）。
export const listBackups = (accountId, region, instanceId, params) =>
  dmops.get(`/v1/instances/${encodeURIComponent(instanceId)}/backups`, {
    params: { account_id: accountId, region, ...params }
  });

// 日志备份列表实时调用 DescribeBinlogFiles，start/end 为 UTC 时间串（yyyy-MM-ddTHH:mmZ）。
export const listBinlogFiles = (accountId, region, instanceId, params) =>
  dmops.get(`/v1/instances/${encodeURIComponent(instanceId)}/binlog-files`, {
    params: { account_id: accountId, region, ...params }
  });

// 跨地域（异地）备份集列表实时调用 DescribeCrossRegionBackups，时间串带秒。
export const listCrossRegionBackups = (accountId, region, instanceId, params) =>
  dmops.get(`/v1/instances/${encodeURIComponent(instanceId)}/cross-region-backups`, {
    params: { account_id: accountId, region, ...params }
  });

// 跨地域（异地）日志备份列表实时调用 DescribeCrossRegionLogBackupFiles。
export const listCrossRegionLogBackupFiles = (accountId, region, instanceId, params) =>
  dmops.get(`/v1/instances/${encodeURIComponent(instanceId)}/cross-region-log-backup-files`, {
    params: { account_id: accountId, region, ...params }
  });

// ---- 备份恢复演练 ----

// 发起演练返回 {id, drill_no}；克隆参数由 preflight 回填，无需再传。
export const createBackupDrill = (data) => dmops.post('/v1/backup-drills', data);

// 演练列表，offline=1 时只看待下线（未确认下线且已产生克隆实例的终态演练）。
export const listBackupDrills = (params) => dmops.get('/v1/backup-drills', { params });

export const getBackupDrill = (drillId) => dmops.get(`/v1/backup-drills/${drillId}`);

// 仅 pending 阶段（克隆请求发出前）可取消。
export const cancelBackupDrill = (drillId) => dmops.post(`/v1/backup-drills/${drillId}/cancel`);

// 人工确认下线：克隆实例已释放。
export const confirmDrillOffline = (drillId) => dmops.post(`/v1/backup-drills/${drillId}/confirm-offline`);

// 发起弹窗前置检查：克隆参数预览 + 通过/未通过检测项。
export const getDrillPreflight = (accountId, region, instanceId) =>
  dmops.get(`/v1/instances/${encodeURIComponent(instanceId)}/drill-preflight`, {
    params: { account_id: accountId, region }
  });

// ---- 注册数据源（源端/克隆实例，JWT 随 Cookie 透传到 dmops 再回调 console）----

// 注册弹窗预填：目标实例连接地址/端口/默认描述（target: source | clone）。
export const getRegisterDsPrefill = (drillId, target) => dmops.get(`/v1/backup-drills/${drillId}/register-ds/${target}/prefill`);

// 测试连接（connectDs 真实建连，不落库）。
export const testRegisterDs = (drillId, target, data) => dmops.post(`/v1/backup-drills/${drillId}/register-ds/${target}/test`, data);

// 提交新增（addDs，dsId 回写演练表）。
export const submitRegisterDs = (drillId, target, data) => dmops.post(`/v1/backup-drills/${drillId}/register-ds/${target}/submit`, data);

// ---- 数据校验（半自动）----

// 库名 + 每库表数量对比（触发即追加，重复校验保留历史）。
export const verifyDbTables = (drillId) => dmops.post(`/v1/backup-drills/${drillId}/verify-db-tables`, null, { timeout: 300000 });

// 选表辅助：候选表及主键/自动更新列标注（全量返回，前端过滤）。
export const getDrillTables = (drillId) => dmops.get(`/v1/backup-drills/${drillId}/drill-tables`, { timeout: 300000 });

// 表数据校验（选定表逐表对比，同步执行）。
export const verifyTableData = (drillId, targetTables) =>
  dmops.post(`/v1/backup-drills/${drillId}/verify-table-data`, { target_tables: targetTables }, { timeout: 300000 });

// 校验历史（含 diff 明细）。
export const listVerifications = (drillId) => dmops.get(`/v1/backup-drills/${drillId}/verifications`);

// ---- 账号凭证 ----

export const getCredential = (accountId) => dmops.get(`/v1/cloud/accounts/${accountId}/credential`);

export const saveCredential = (accountId, data) => dmops.put(`/v1/cloud/accounts/${accountId}/credential`, data);

export const deleteCredential = (accountId) => dmops.delete(`/v1/cloud/accounts/${accountId}/credential`);

// ---- 配置管理 ----

// 全量列表，无分页；加密项的 config_value 脱敏为 ******。
export const listConfigs = (params) => dmops.get('/v1/configs', { params });

// 详情返回解密后的明文，供编辑表单回填。
export const getConfig = (configId) => dmops.get(`/v1/configs/${configId}`);

export const createConfig = (data) => dmops.post('/v1/configs', data);

export const updateConfig = (configId, data) => dmops.put(`/v1/configs/${configId}`, data);

export const deleteConfig = (configId) => dmops.delete(`/v1/configs/${configId}`);

export default dmops;
