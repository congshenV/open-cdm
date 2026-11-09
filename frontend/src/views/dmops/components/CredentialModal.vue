<template>
  <a-modal :open="open" :title="$t('she-zhi-ping-zheng')" :width="620" :mask-closable="false" @cancel="close">
    <div v-if="account" class="dmops-credential-account">
      <span class="dmops-credential-account__name">{{ account.name }}</span>
      <span class="dmops-muted">{{ account.cloud_account_id }}</span>
      <a-tag v-if="configured" color="green">{{ $t('yi-pei-zhi') }}</a-tag>
    </div>

    <a-alert
      v-if="unsupportedType"
      class="dmops-credential-alert"
      type="warning"
      show-icon
      :message="$t('dang-qian-ren-zheng-fang-shi-bu-zhi-chi', { type: existingTypeLabel })"
    />

    <a-spin :spinning="loading">
      <a-form class="dmops-form" layout="vertical">
        <a-form-item :label="$t('ren-zheng-fang-shi')" required>
          <a-select v-model:value="form.credential_type" :placeholder="$t('qing-xuan-ze-ren-zheng-fang-shi')">
            <a-select-option v-for="type in supportedTypes" :key="type" :value="type">
              {{ typeLabel(type) }}
            </a-select-option>
          </a-select>
        </a-form-item>

        <!-- default：运行环境默认凭据链（ACK RRSA / 实例 RAM 角色），无需填写凭据 -->
        <a-alert
          v-if="form.credential_type === 'default'"
          class="dmops-credential-alert"
          type="info"
          show-icon
          :message="$t('mo-ren-ping-zheng-shuo-ming')"
        />

        <template v-if="form.credential_type && form.credential_type !== 'default'">
          <a-form-item :label="$t('access-key-id')" :required="typeChanged">
            <a-input v-model:value="form.access_key_id" :maxlength="128" :placeholder="$t('access-key-id')" />
            <div v-if="maskedAccessKeyId" class="dmops-field-hint">{{ $t('dang-qian-access-key-id', { id: maskedAccessKeyId }) }}</div>
          </a-form-item>

          <a-form-item :label="$t('access-key-secret')" :required="typeChanged">
            <a-input-password v-model:value="form.access_key_secret" :maxlength="256" :placeholder="secretPlaceholder" />
          </a-form-item>

          <a-form-item v-if="form.credential_type === 'sts'" :label="$t('security-token')" :required="typeChanged">
            <a-textarea v-model:value="form.security_token" :rows="2" :maxlength="4096" :placeholder="tokenPlaceholder" />
          </a-form-item>

          <template v-if="form.credential_type === 'ram_role_arn'">
            <a-form-item :label="$t('jiao-se-arn')" :required="typeChanged">
              <a-input v-model:value="form.role_arn" :maxlength="256" :placeholder="$t('jiao-se-arn-zhan-wei')" />
            </a-form-item>
            <a-form-item :label="$t('hui-hua-ming-cheng')">
              <a-input v-model:value="form.role_session_name" :maxlength="64" :placeholder="$t('hui-hua-ming-cheng-zhan-wei')" />
            </a-form-item>
            <a-form-item :label="$t('hui-hua-shi-chang-miao')">
              <a-input v-model:value="form.role_session_expiration" :maxlength="4" :placeholder="$t('hui-hua-shi-chang-zhan-wei')" />
            </a-form-item>
          </template>
        </template>

        <a-form-item v-if="form.credential_type" :label="$t('qi-yong')">
          <a-switch v-model:checked="form.enabled" />
        </a-form-item>
      </a-form>
    </a-spin>

    <template #footer>
      <div class="dmops-modal-footer">
        <a-popconfirm v-if="configured" :title="$t('que-ding-shan-chu-gai-ping-zheng-ma')" @confirm="handleDelete">
          <a-button danger :loading="deleting">{{ $t('shan-chu-ping-zheng') }}</a-button>
        </a-popconfirm>
        <div class="dmops-modal-footer__right">
          <a-button @click="close">{{ $t('qu-xiao') }}</a-button>
          <a-button type="primary" :loading="saving" @click="submit">{{ $t('bao-cun') }}</a-button>
        </div>
      </div>
    </template>
  </a-modal>
</template>

<script>
import Toast from '@/utils/toast';
import { deleteCredential, getCredential, saveCredential } from '@/services/http/dmops';
import { CREDENTIAL_TYPES, credentialTypeLabel } from '@/views/dmops/utils/credential';

// 页面维护常用认证方式，其余类型后端支持但不在表单里维护
const SUPPORTED_TYPES = CREDENTIAL_TYPES;
const TYPE_FIELDS = {
  access_key: ['access_key_id', 'access_key_secret'],
  sts: ['access_key_id', 'access_key_secret', 'security_token'],
  ram_role_arn: ['access_key_id', 'access_key_secret', 'role_arn', 'role_session_name', 'role_session_expiration'],
  // default：运行环境默认凭据链（ACK RRSA 等），无需任何字段。
  default: []
};
const REQUIRED_FIELDS = {
  access_key: ['access_key_id', 'access_key_secret'],
  sts: ['access_key_id', 'access_key_secret', 'security_token'],
  ram_role_arn: ['access_key_id', 'access_key_secret', 'role_arn'],
  default: []
};
const EMPTY_FORM = () => ({
  credential_type: 'access_key',
  access_key_id: '',
  access_key_secret: '',
  security_token: '',
  role_arn: '',
  role_session_name: '',
  role_session_expiration: '3600',
  enabled: true
});

export default {
  name: 'DmOpsCredentialModal',
  props: {
    open: {
      type: Boolean,
      default: false
    },
    account: {
      type: Object,
      default: null
    }
  },
  emits: ['update:open', 'saved'],
  data() {
    return {
      supportedTypes: SUPPORTED_TYPES,
      loading: false,
      saving: false,
      deleting: false,
      configured: false,
      existingType: '',
      maskedAccessKeyId: '',
      secretSet: false,
      tokenSet: false,
      form: EMPTY_FORM()
    };
  },
  computed: {
    existingTypeLabel() {
      return this.typeLabel(this.existingType);
    },
    unsupportedType() {
      return this.configured && !!this.existingType && !SUPPORTED_TYPES.includes(this.existingType);
    },
    // 新建或切换认证方式时，必填项必须重新填写；同类型编辑留空表示沿用旧值
    typeChanged() {
      return !this.configured || this.form.credential_type !== this.existingType;
    },
    secretPlaceholder() {
      return this.secretSet ? this.$t('mi-yao-yi-pei-zhi-liu-kong-bu-xiu-gai') : this.$t('access-key-secret');
    },
    tokenPlaceholder() {
      return this.tokenSet ? this.$t('mi-yao-yi-pei-zhi-liu-kong-bu-xiu-gai') : this.$t('security-token');
    }
  },
  watch: {
    open(value) {
      if (value) {
        this.load();
      }
    }
  },
  methods: {
    typeLabel(type) {
      return credentialTypeLabel(this.$t, type);
    },
    close() {
      this.$emit('update:open', false);
    },
    async load() {
      if (!this.account || !this.account.id) {
        return;
      }

      this.loading = true;
      try {
        const data = await getCredential(this.account.id);
        this.configured = !!data.configured;
        this.maskedAccessKeyId = data.access_key_id_masked || '';
        this.secretSet = !!data.access_key_secret_set;
        this.tokenSet = !!data.security_token_set;
        this.existingType = data.credential_type || '';

        if (this.configured) {
          this.form = {
            credential_type: SUPPORTED_TYPES.includes(this.existingType) ? this.existingType : '',
            access_key_id: '',
            access_key_secret: '',
            security_token: '',
            role_arn: data.role_arn || '',
            role_session_name: data.role_session_name || '',
            role_session_expiration: data.role_session_expiration ? String(data.role_session_expiration) : '3600',
            enabled: !!data.enabled
          };
          return;
        }

        this.existingType = '';
        this.form = EMPTY_FORM();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.loading = false;
      }
    },
    validate() {
      const type = this.form.credential_type;
      if (!type) {
        Toast.error(this.$t('qing-xuan-ze-ren-zheng-fang-shi'));
        return false;
      }

      if (this.typeChanged) {
        const missing = REQUIRED_FIELDS[type].filter((field) => !String(this.form[field] || '').trim());
        if (missing.length > 0) {
          Toast.error(this.$t('qing-wan-shan-bi-tian-xiang'));
          return false;
        }
      }

      const expiration = String(this.form.role_session_expiration || '').trim();
      if (type === 'ram_role_arn' && expiration) {
        const value = Number(expiration);
        if (!Number.isInteger(value) || value < 900 || value > 3600) {
          Toast.error(this.$t('hui-hua-shi-chang-fan-wei'));
          return false;
        }
      }

      return true;
    },
    buildPayload() {
      const type = this.form.credential_type;
      const payload = {
        credential_type: type,
        enabled: this.form.enabled
      };
      TYPE_FIELDS[type].forEach((field) => {
        const value = String(this.form[field] || '').trim();
        if (value !== '') {
          payload[field] = value;
        }
      });
      return payload;
    },
    async submit() {
      if (!this.account || !this.validate()) {
        return;
      }

      this.saving = true;
      try {
        await saveCredential(this.account.id, this.buildPayload());
        Toast.success(this.$t('cao-zuo-cheng-gong'));
        this.$emit('saved');
        this.close();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.saving = false;
      }
    },
    async handleDelete() {
      if (!this.account) {
        return;
      }

      this.deleting = true;
      try {
        await deleteCredential(this.account.id);
        Toast.success(this.$t('cao-zuo-cheng-gong'));
        this.$emit('saved');
        this.close();
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.deleting = false;
      }
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-credential-account {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;

  &__name {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
  }
}

.dmops-credential-alert {
  margin-bottom: 12px;
}

.dmops-form {
  padding-top: 4px;
}

.dmops-field-hint {
  margin-top: 4px;
  font-size: 12px;
  line-height: 18px;
  color: var(--text-tertiary);
}

.dmops-modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;

  &__right {
    display: flex;
    gap: 8px;
  }
}
</style>
