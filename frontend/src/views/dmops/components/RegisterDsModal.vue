<template>
  <!--
    注册数据源弹窗（源端/克隆实例）。
    流程：打开时 prefill 预填（实例信息）→ 用户补全账号密码 → 「测试连接」
    （connectDs 真实建连）→ 通过后「提交新增」（addDs，dsId 回写演练表）。
    密码仅随请求传给 console，不落库。
  -->
  <a-modal :open="open" :title="title" :width="560" :mask-closable="false" @cancel="close">
    <a-spin :spinning="prefillLoading">
      <a-alert v-if="targetDesc" class="dmops-register-alert" type="info" show-icon :message="targetDesc" />
      <!-- 已存在同 host 数据源：提交时将直接复用，不重复创建 -->
      <a-alert
        v-if="existingDs"
        class="dmops-register-alert"
        type="warning"
        show-icon
        :message="$t('gai-di-zhi-yi-you-shu-ju-yuan', { dsId: existingDs.id, desc: existingDs.instance_desc || '-' })"
      />

      <a-form class="dmops-form" layout="vertical">
        <a-form-item :label="$t('lian-jie-di-zhi')" required>
          <a-input v-model:value="form.host" :placeholder="$t('shi-li-lian-jie-di-zhi-zhan-wei')" />
        </a-form-item>

        <a-form-item :label="$t('duan-kou')" required>
          <a-input v-model:value="form.port" style="width: 160px" :maxlength="5" />
        </a-form-item>

        <a-form-item :label="$t('shu-ju-ku-lei-xing')">
          <span>{{ engineText }}</span>
          <span class="dmops-field-hint">{{ driverText }}</span>
        </a-form-item>

        <a-form-item :label="$t('ji-qun')" required>
          <a-select v-model:value="form.cluster_id" style="width: 240px" :placeholder="$t('qing-xuan-ze-ji-qun')">
            <a-select-option v-for="cluster in prefilled.clusters || []" :key="cluster.id" :value="cluster.id">
              {{ `${cluster.cluster_desc}（${cluster.id}）` }}
            </a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item :label="$t('huan-jing')" required>
          <a-select v-model:value="form.env_id" style="width: 240px" :placeholder="$t('qing-xuan-ze-huan-jing')">
            <a-select-option v-for="env in prefilled.envs || []" :key="env.id" :value="env.id">
              {{ `${env.env_name}（${env.id}）` }}
            </a-select-option>
          </a-select>
        </a-form-item>

        <a-form-item :label="$t('lian-jie-zhang-hao')" required>
          <a-input v-model:value="form.username" :maxlength="128" :placeholder="$t('yong-hu-ming')" />
        </a-form-item>

        <a-form-item :label="$t('lian-jie-mi-ma')" required>
          <a-input-password v-model:value="form.password" :maxlength="256" :placeholder="$t('mi-ma')" />
        </a-form-item>

        <a-form-item :label="$t('shu-ju-yuan-ming-cheng')">
          <a-input v-model:value="form.instance_desc" :maxlength="255" :placeholder="defaultDesc" />
          <div class="dmops-field-hint">{{ $t('shu-ju-yuan-ming-cheng-ti-shi') }}</div>
        </a-form-item>
      </a-form>
    </a-spin>

    <template #footer>
      <a-button @click="close">{{ $t('qu-xiao') }}</a-button>
      <a-button :loading="testing" :disabled="!formValid" @click="handleTest">
        {{ $t('ce-shi-lian-jie') }}
      </a-button>
      <a-button type="primary" :loading="submitting" :disabled="!formValid || !tested" @click="handleSubmit">
        {{ $t('ti-jiao-xin-zeng') }}
      </a-button>
    </template>
  </a-modal>
</template>

<script>
import Toast from '@/utils/toast';
import { getRegisterDsPrefill, submitRegisterDs, testRegisterDs } from '@/services/http/dmops';

export default {
  name: 'DmOpsRegisterDsModal',
  props: {
    open: {
      type: Boolean,
      default: false
    },
    // { drillId, target: 'source' | 'clone' }
    context: {
      type: Object,
      default: null
    }
  },
  emits: ['update:open', 'registered'],
  data() {
    return {
      prefillLoading: false,
      testing: false,
      submitting: false,
      tested: false,
      prefilled: {},
      form: {
        host: '',
        port: '',
        engine: '',
        cluster_id: null,
        env_id: null,
        username: '',
        password: '',
        instance_desc: ''
      }
    };
  },
  computed: {
    target() {
      return (this.context && this.context.target) || 'source';
    },
    title() {
      if (this.target === 'clone') {
        return this.$t('zhu-ce-ke-long-shu-ju-yuan');
      }
      return this.$t('zhu-ce-yuan-duan-shu-ju-yuan');
    },
    targetDesc() {
      if (this.target === 'clone') {
        return this.$t('zhu-ce-ke-long-shu-ju-yuan-shuo-ming');
      }
      return this.$t('zhu-ce-yuan-duan-shu-ju-yuan-shuo-ming');
    },
    // 同 host 已有数据源（prefill 时服务端按 dm_ds 查得），提交时将复用。
    existingDs() {
      return this.prefilled && this.prefilled.existing_ds ? this.prefilled.existing_ds : null;
    },
    engineText() {
      return this.form.engine || '-';
    },
    driverText() {
      const driver = `${this.prefilled.driver_family || ''} ${this.prefilled.driver_version || ''}`.trim();
      return driver ? `· ${driver}` : '';
    },
    defaultDesc() {
      return (this.prefilled && this.prefilled.instance_desc) || '';
    },
    formValid() {
      return Boolean(this.form.host && this.form.port && this.form.cluster_id && this.form.env_id && this.form.username && this.form.password);
    }
  },
  watch: {
    open(value) {
      if (value) {
        this.reset();
        this.loadPrefill();
      }
    }
  },
  methods: {
    reset() {
      this.tested = false;
      this.prefilled = {};
      this.form = {
        host: '',
        port: '',
        engine: '',
        cluster_id: null,
        env_id: null,
        username: '',
        password: '',
        instance_desc: ''
      };
    },
    close() {
      this.$emit('update:open', false);
    },
    async loadPrefill() {
      const context = this.context;
      if (!context || !context.drillId) {
        return;
      }
      this.prefillLoading = true;
      try {
        const data = await getRegisterDsPrefill(context.drillId, this.target);
        this.prefilled = data;
        this.form.host = data.host || '';
        this.form.port = data.port || '';
        this.form.engine = data.ds_type || '';
        this.form.cluster_id = data.cluster_id || null;
        this.form.env_id = data.env_id || null;
        // 默认账号密码来自配置管理 rds_default_u_p（服务端预填下发），可改。
        this.form.username = data.username || '';
        this.form.password = data.password || '';
        this.form.instance_desc = data.instance_desc || '';
      } catch (error) {
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.prefillLoading = false;
      }
    },
    buildPayload() {
      return {
        host: this.form.host.trim(),
        port: this.form.port.trim(),
        engine: this.form.engine,
        cluster_id: this.form.cluster_id,
        env_id: this.form.env_id,
        username: this.form.username.trim(),
        password: this.form.password,
        instance_desc: this.form.instance_desc.trim(),
        driver_family: this.prefilled.driver_family || '',
        driver_version: this.prefilled.driver_version || ''
      };
    },
    async handleTest() {
      const context = this.context;
      if (!context || !this.formValid || this.testing) {
        return;
      }
      this.testing = true;
      try {
        await testRegisterDs(context.drillId, this.target, this.buildPayload());
        this.tested = true;
        Toast.success(this.$t('lian-jie-ce-shi-tong-guo'));
      } catch (error) {
        this.tested = false;
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.testing = false;
      }
    },
    async handleSubmit() {
      const context = this.context;
      if (!context || !this.formValid || !this.tested || this.submitting) {
        return;
      }
      this.submitting = true;
      try {
        const data = await submitRegisterDs(context.drillId, this.target, this.buildPayload());
        // 以服务端提交时的查重结果为准（data.reused），不依赖 prefill 时的预检状态。
        if (data.reused) {
          Toast.success(this.$t('fu-yong-yi-you-shu-ju-yuan', { dsId: data.ds_id }));
        } else {
          Toast.success(this.$t('zhu-ce-cheng-gong', { dsId: data.ds_id }));
        }
        this.$emit('registered', data);
        this.close();
      } catch (error) {
        // 提交失败（如 connectDs 重测失败）时测试态作废，需重新测试。
        this.tested = false;
        Toast.error(error.message || this.$t('yun-wei-jie-kou-diao-yong-shi-bai'));
      } finally {
        this.submitting = false;
      }
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-register-alert {
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
</style>
