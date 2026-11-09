/**
 * 认证方式在页面上的展示与可用范围。
 *
 * 后端支持 8 种，页面维护常用四种；其余类型遇到时按原始值展示，并提示需要切换。
 * default = 运行环境默认凭据链（ACK RRSA / 实例 RAM 角色 / profile 等），无需填写凭据，
 * 适合 dmops 部署在 ACK 且访问自身所在账号的场景。
 */
export const CREDENTIAL_TYPES = ['access_key', 'sts', 'ram_role_arn', 'default'];

const CREDENTIAL_TYPE_KEYS = {
  access_key: 'access-key',
  sts: 'sts-lin-shi-ping-zheng',
  ram_role_arn: 'ram-jiao-se',
  default: 'mo-ren-ping-zheng'
};

export function credentialTypeLabel(t, type) {
  const key = CREDENTIAL_TYPE_KEYS[type];
  return key ? t(key) : type || '';
}
