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

export default dmops;
