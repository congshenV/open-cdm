<template>
  <!--
    运维控制台外壳。

    整体结构照搬控制台（app-layout：左侧栏 + 卡片内容区），只是：
      - 侧边栏换成 dmops 自己的菜单（实例列表 / 配置管理）
      - 内容区由 dmops 的子路由渲染
    与 CloudDM 主站不共用 store 与菜单，后续整体替换 dmops 前端时只动这一个目录。
  -->
  <div class="app-layout dmops-shell">
    <aside class="app-sidebar">
      <div class="app-sidebar-brand" :title="$t('yun-wei-kong-zhi-tai')" @click="handleGoInstance">
        <AppBrandLogo />
      </div>

      <nav class="app-sidebar-nav">
        <div class="app-sidebar-section">
          <router-link
            v-for="item in navItems"
            :key="item.key"
            :to="item.to"
            :aria-label="item.label"
            :title="item.label"
            class="app-sidebar-item"
            :class="{ 'is-active': activeKey === item.key }"
          >
            <CustomIcon :type="item.icon" size="16px" />
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </nav>
    </aside>

    <main class="app-main">
      <div class="app-main-body">
        <div class="app-main-card">
          <header class="app-content-header">
            <div class="app-content-header__left">
              <h1 class="app-content-header__title">
                <router-link to="/dmops/instance" class="app-content-header__crumb">{{ $t('yun-wei-kong-zhi-tai') }}</router-link>
                <span class="app-content-header__separator">/</span>
                <span class="app-content-header__crumb is-current">{{ currentTitle }}</span>
              </h1>
            </div>
            <div class="app-content-header__right">
              <button type="button" class="app-content-header__link" :title="$t('fan-hui-kong-zhi-tai')" @click="handleBackToConsole">
                <CustomIcon type="icon-v2-ArrowLeftSimple" size="14px" />
                <span>{{ $t('fan-hui-kong-zhi-tai') }}</span>
              </button>
              <AppUserActions compact />
            </div>
          </header>
          <div class="app-main-card__body">
            <router-view />
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script>
import { mapState } from 'vuex';
import AppBrandLogo from '@/components/layout/AppBrandLogo';
import AppUserActions from '@/components/layout/AppUserActions';
import { resolveWorkbenchFallbackPath, resolveWorkbenchRoute } from '@/utils/workbenchRoute';

export default {
  name: 'DmOps',
  components: { AppBrandLogo, AppUserActions },
  computed: {
    ...mapState(['mySystemMenuItems', 'userInfo']),
    navItems() {
      return [
        { key: 'instance', to: '/dmops/instance', icon: 'icon-v2-DataBase2', label: this.$t('shi-li-lie-biao') },
        { key: 'config', to: '/dmops/config', icon: 'icon-v2-DSENV', label: this.$t('pei-zhi-guan-li') }
      ];
    },
    activeKey() {
      const matched = this.navItems.find((item) => this.$route.path.startsWith(item.to));
      return matched ? matched.key : 'instance';
    },
    currentTitle() {
      const matched = this.navItems.find((item) => item.key === this.activeKey);
      return matched ? matched.label : '';
    }
  },
  methods: {
    handleGoInstance() {
      if (this.$route.path !== '/dmops/instance') {
        this.$router.push({ path: '/dmops/instance' }).catch(() => {});
      }
    },
    handleBackToConsole() {
      // 与控制台里「返回工作台」保持一致：回到上次访问的工作台页面，避免丢上下文
      const fallback = resolveWorkbenchFallbackPath(this.mySystemMenuItems);
      const target = resolveWorkbenchRoute(fallback, this.userInfo?.uid, this.mySystemMenuItems);
      this.$router.push(target).catch(() => {});
    }
  }
};
</script>

<style lang="less" scoped>
.dmops-shell {
  width: 100%;
}
</style>
