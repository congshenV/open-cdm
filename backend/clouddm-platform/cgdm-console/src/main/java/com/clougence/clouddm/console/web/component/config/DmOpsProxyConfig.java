/*
 * Copyright 2026 杭州开云集致科技有限公司
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.clougence.clouddm.console.web.component.config;

import java.util.concurrent.TimeUnit;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;

import com.clougence.utils.StringUtils;

import jakarta.annotation.PostConstruct;
import lombok.Getter;
import lombok.Setter;
import lombok.extern.slf4j.Slf4j;
import okhttp3.OkHttpClient;

/**
 * Config for dmops proxy. dmops is an independent service deployed on another host,
 * console forwards /api/dmops/** requests to it.
 *
 * @author congshen
 */
@Getter
@Setter
@Slf4j
@Configuration
public class DmOpsProxyConfig {

    /** master switch, dmops proxy is disabled by default. */
    @Value("${dmops.proxy.enabled:false}")
    private boolean      enabled;
    /** base url of dmops, the /api/dmops prefix is replaced by it. */
    @Value("${dmops.proxy.base-url:}")
    private String       baseUrl;
    @Value("${dmops.proxy.connect-timeout-ms:3000}")
    private int          connectTimeoutMs;
    /** instance sync fans out over all regions, it needs the same 180s budget as the frontend and gunicorn. */
    @Value("${dmops.proxy.read-timeout-ms:180000}")
    private int          readTimeoutMs;
    /** shared secret used to sign the forwarded user identity. */
    @Value("${dmops.proxy.identity.secret:}")
    private String       identitySecret;
    /** only paths start with these prefixes are forwarded, empty means allow all. */
    @Value("${dmops.proxy.allowed-path:/v1/}")
    private String       allowedPath;

    private OkHttpClient httpClient;

    @PostConstruct
    public void init() {
        if (!this.enabled) {
            log.info("[DmOpsProxy] disabled.");
            return;
        }
        if (StringUtils.isBlank(this.baseUrl)) {
            log.error("[DmOpsProxy] enabled but dmops.proxy.base-url is blank, all /api/dmops requests will be rejected.");
            return;
        }
        // without a secret the forwarded user identity cannot be verified by dmops,
        // so refuse to start the proxy rather than silently passing unsigned identity.
        if (StringUtils.isBlank(this.identitySecret)) {
            log.error("[DmOpsProxy] enabled but dmops.proxy.identity.secret is blank, all /api/dmops requests will be rejected.");
            return;
        }

        this.baseUrl = StringUtils.removeEnd(this.baseUrl, "/");
        this.httpClient = new OkHttpClient.Builder().connectTimeout(this.connectTimeoutMs, TimeUnit.MILLISECONDS)
            .readTimeout(this.readTimeoutMs, TimeUnit.MILLISECONDS)
            .writeTimeout(this.readTimeoutMs, TimeUnit.MILLISECONDS)
            .followRedirects(false)
            .build();
        log.info("[DmOpsProxy] enabled, baseUrl=" + this.baseUrl + ", allowedPath=" + this.allowedPath);
    }

    /** proxy is usable only when enabled and all required config is present. */
    public boolean isReady() {
        return this.enabled && this.httpClient != null && StringUtils.isNotBlank(this.baseUrl) && StringUtils.isNotBlank(this.identitySecret);
    }
}
