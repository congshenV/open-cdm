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
package com.clougence.clouddm.console.web.controller.dmops;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.auth0.jwt.interfaces.DecodedJWT;
import com.clougence.clouddm.console.web.component.config.DmOpsProxyConfig;
import com.clougence.clouddm.console.web.global.jwtsession.JwtService;
import com.clougence.clouddm.console.web.global.jwtsession.RequestAuth;
import com.clougence.rdp.component.openapi.OpenApiSigner;
import com.clougence.utils.StringUtils;
import com.clougence.utils.io.IOUtils;

import jakarta.annotation.Resource;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import okhttp3.Headers;
import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;

/**
 * Reverse proxy for dmops: forwards /api/dmops/** to an independently deployed dmops service.
 *
 * <p>This controller only does three things: authenticate the caller, rewrite the path and pass
 * through the request/response. There is no business logic here, dmops owns all of it.</p>
 *
 * @author congshen
 */
@Slf4j
@RestController
@RequestMapping(DmOpsProxyController.URL_PREFIX)
public class DmOpsProxyController {

    public static final String       URL_PREFIX = "/api/dmops";

    /**
     * Headers that must not be forwarded to dmops or copied back, they are connection
     * scoped or will corrupt the proxied response.
     */
    private static final Set<String> HOP_BY_HOP = new HashSet<>(
        Arrays.asList("connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length"));

    /**
     * OkHttp refuses POST/PUT/PATCH without a RequestBody, even when the caller sent an empty body
     * (the dmops sync endpoint is exactly that: POST with Content-Length: 0). Give them an explicit
     * empty body instead of null.
     */
    private static final Set<String> BODY_REQUIRED_METHODS = new HashSet<>(Arrays.asList("POST", "PUT", "PATCH", "PROPPATCH", "REPORT"));

    @Resource
    private DmOpsProxyConfig         config;
    @Resource
    private JwtService               jwtService;

    @RequestAuth(strategy = RequestAuth.AuthStrategy.Ignore)
    @RequestMapping("/**")
    public void proxy(HttpServletRequest request, HttpServletResponse response) throws IOException {
        if (!this.config.isReady()) {
            log.warn("[DmOpsProxy] dmops is not configured, request rejected. uri=" + request.getRequestURI());
            writeError(response, HttpServletResponse.SC_SERVICE_UNAVAILABLE, "dmops is not configured.");
            return;
        }

        // console JwtManager skips jwt verify for any uri not starting with /api/entry,
        // so authentication has to be done here.
        DecodedJWT jwt = this.jwtService.verify(request);
        if (jwt == null || StringUtils.isBlank(jwt.getId())) {
            log.warn("[DmOpsProxy] unauthorized request. uri=" + request.getRequestURI());
            writeError(response, HttpServletResponse.SC_UNAUTHORIZED, "NotLogin.");
            return;
        }
        String uid = jwt.getId();

        // request.getRequestURI() includes the servlet context path, so strip the prefix
        // by its position rather than assuming the uri starts with it.
        String requestUri = request.getRequestURI();
        int prefixIndex = requestUri.indexOf(URL_PREFIX);
        if (prefixIndex < 0) {
            writeError(response, HttpServletResponse.SC_BAD_REQUEST, "unexpected request uri.");
            return;
        }
        String restPath = requestUri.substring(prefixIndex + URL_PREFIX.length());
        if (!isPathAllowed(restPath)) {
            log.warn("[DmOpsProxy] path is not allowed. uri=" + requestUri);
            writeError(response, HttpServletResponse.SC_FORBIDDEN, "path is not allowed by dmops proxy.");
            return;
        }

        String targetUrl = buildTargetUrl(restPath, request.getQueryString());
        Request okRequest;
        try {
            okRequest = buildOkRequest(request, targetUrl, uid);
        } catch (IOException e) {
            String msg = "[DmOpsProxy] failed to read request body. target=" + targetUrl;
            log.error(msg, e);
            writeError(response, HttpServletResponse.SC_BAD_REQUEST, "read request body failed.");
            return;
        }

        long start = System.currentTimeMillis();
        try (Response okResponse = this.config.getHttpClient().newCall(okRequest).execute()) {
            copyResponse(okResponse, response);
            log.info("[DmOpsProxy] " + request.getMethod() + " " + targetUrl + " -> " + okResponse.code() + ", cost=" + (System.currentTimeMillis() - start) + "ms, uid=" + uid);
        } catch (IOException e) {
            String msg = "[DmOpsProxy] failed to reach dmops. target=" + targetUrl + ", msg:" + e.getMessage();
            log.error(msg, e);
            if (!response.isCommitted()) {
                writeError(response, HttpServletResponse.SC_BAD_GATEWAY, "dmops unreachable.");
            }
        }
    }

    private boolean isPathAllowed(String restPath) {
        // normalize before matching, otherwise "/v1/../../admin" would still pass the "/v1/" prefix check
        // while OkHttp resolves the dot segments and reaches "/admin".
        if (hasPathTraversal(restPath)) {
            return false;
        }

        String allowed = this.config.getAllowedPath();
        if (StringUtils.isBlank(allowed)) {
            return true;
        }

        for (String prefix : allowed.split(",")) {
            String p = StringUtils.trim(prefix);
            if (StringUtils.isNotBlank(p) && StringUtils.startsWithIgnoreCase(restPath, p)) {
                return true;
            }
        }
        return false;
    }

    /** reject dot segments, encoded dots and backslashes before the path is handed to the http client. */
    private boolean hasPathTraversal(String restPath) {
        if (restPath.contains("..") || restPath.contains("\\")) {
            return true;
        }

        String lower = restPath.toLowerCase();
        return lower.contains("%2e") || lower.contains("%00") || lower.contains("%5c") || lower.contains("%2f");
    }

    private String buildTargetUrl(String restPath, String queryString) {
        String url = this.config.getBaseUrl() + restPath;
        if (StringUtils.isNotBlank(queryString)) {
            url = url + "?" + queryString;
        }
        return url;
    }

    private Request buildOkRequest(HttpServletRequest request, String targetUrl, String uid) throws IOException {
        String method = request.getMethod();
        RequestBody body = null;
        if (!StringUtils.equalsIgnoreCase(method, "GET") && !StringUtils.equalsIgnoreCase(method, "HEAD")) {
            byte[] bytes = IOUtils.toByteArray(request.getInputStream());
            if (bytes.length > 0 || BODY_REQUIRED_METHODS.contains(method.toUpperCase())) {
                String contentType = request.getContentType();
                MediaType mediaType = contentType == null ? null : MediaType.parse(contentType);
                body = RequestBody.create(bytes, mediaType);
            }
        }

        Headers.Builder headerBuilder = new Headers.Builder();
        for (String name : Collections.list(request.getHeaderNames())) {
            if (HOP_BY_HOP.contains(name.toLowerCase())) {
                continue;
            }
            for (String value : Collections.list(request.getHeaders(name))) {
                headerBuilder.add(name, value);
            }
        }
        // always overwrite these headers so a client cannot forge them,
        // Headers.Builder.set() replaces any value collected from the incoming request.
        headerBuilder.set("X-DmOps-User", uid);
        headerBuilder.set("X-DmOps-Signature", signIdentity(uid));
        headerBuilder.set("X-Request-Id", UUID.randomUUID().toString());

        return new Request.Builder().url(HttpUrl.get(targetUrl)).headers(headerBuilder.build()).method(method, body).build();
    }

    private String signIdentity(String uid) {
        return OpenApiSigner.signString(uid, this.config.getIdentitySecret());
    }

    private void copyResponse(Response okResponse, HttpServletResponse response) throws IOException {
        response.setStatus(okResponse.code());

        for (Map.Entry<String, List<String>> entry : okResponse.headers().toMultimap().entrySet()) {
            String name = entry.getKey();
            if (HOP_BY_HOP.contains(name.toLowerCase())) {
                continue;
            }
            for (String value : entry.getValue()) {
                response.addHeader(name, value);
            }
        }

        ResponseBody body = okResponse.body();
        if (body == null) {
            response.flushBuffer();
            return;
        }

        try (InputStream in = body.byteStream(); OutputStream out = response.getOutputStream()) {
            IOUtils.copy(in, out);
            out.flush();
        }
    }

    private void writeError(HttpServletResponse response, int status, String message) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"success\":false,\"errorCode\":" + status + ",\"message\":\"" + message + "\"}");
        response.getWriter().flush();
    }
}
