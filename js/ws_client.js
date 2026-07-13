/**
 * VoiceCall WebUI - WebSocket 客户端
 *
 * 负责与插件的 WebSocket 服务端通信。
 * 支持自动重连、消息分发、连接状态管理。
 */

function buildWsUrl() {
    const params = new URLSearchParams(window.location.search);
    const explicit = params.get('ws');
    if (explicit) return explicit;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || '127.0.0.1:6888';
    return `${protocol}//${host}/ws`;
}

const WS_URL = buildWsUrl();
const RECONNECT_DELAY = 3000;   // 重连间隔 (ms)
const MAX_RECONNECT = 10;       // 最大重连次数

export class WsClient {
    constructor() {
        this.ws = null;
        this.reconnectCount = 0;
        this.reconnectTimer = null;
        this.handlers = {};       // type → callback[]
        this.connected = false;
    }

    // ── 事件注册 ────────────────────────────────────

    /**
     * 注册消息处理器
     * @param {string} type - 消息类型
     * @param {Function} callback - async (payload) => void
     */
    on(type, callback) {
        if (!this.handlers[type]) {
            this.handlers[type] = [];
        }
        this.handlers[type].push(callback);
    }

    /**
     * 注册一次性消息处理器
     */
    once(type, callback) {
        const wrapper = (payload) => {
            callback(payload);
            this.off(type, wrapper);
        };
        this.on(type, wrapper);
    }

    /**
     * 移除消息处理器
     */
    off(type, callback) {
        if (this.handlers[type]) {
            this.handlers[type] = this.handlers[type].filter(cb => cb !== callback);
        }
    }

    // ── 连接管理 ────────────────────────────────────

    /**
     * 建立 WebSocket 连接
     */
    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        console.log(`[WS] 正在连接 ${WS_URL} ...`);
        this.ws = new WebSocket(WS_URL);

        this.ws.onopen = () => {
            console.log('[WS] 已连接');
            this.connected = true;
            this.reconnectCount = 0;
            this._dispatch('__connected__', {});
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const type = data.type || 'unknown';
                const payload = data.payload || {};
                console.debug(`[WS] 收到: ${type}`, payload);
                this._dispatch(type, payload);
            } catch (e) {
                console.error('[WS] 消息解析失败:', e);
            }
        };

        this.ws.onclose = (event) => {
            console.log(`[WS] 连接关闭 (code=${event.code})`);
            this.connected = false;
            this._dispatch('__disconnected__', { code: event.code, reason: event.reason });
            this._tryReconnect();
        };

        this.ws.onerror = (error) => {
            console.error('[WS] 连接错误:', error);
        };
    }

    /**
     * 断开连接
     */
    disconnect() {
        this._clearReconnect();
        if (this.ws) {
            this.ws.onclose = null;  // 阻止重连
            this.ws.close();
            this.ws = null;
        }
        this.connected = false;
    }

    // ── 发送消息 ────────────────────────────────────

    /**
     * 发送消息到插件
     * @param {string} type - 消息类型
     * @param {object} payload - 消息负载
     */
    send(type, payload = {}) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            console.warn('[WS] 未连接，无法发送:', type);
            return false;
        }
        const msg = JSON.stringify({ type, payload });
        this.ws.send(msg);
        console.debug(`[WS] 发送: ${type}`, payload);
        return true;
    }

    // ── 便捷发送方法 ────────────────────────────────

    /** 用户拨打电话 */
    sendUserCall() {
        return this.send('user_call', {});
    }

    /** 接听来电 */
    sendAnswerCall(callId) {
        return this.send('answer_call', { call_id: callId });
    }

    /** 拒绝来电 */
    sendRejectCall(callId) {
        return this.send('reject_call', { call_id: callId });
    }

    /** 挂断通话 */
    sendHangup(callId) {
        return this.send('hangup', { call_id: callId });
    }

    /** 发送音频数据 */
    sendAudioData(callId, audioBase64, format = 'webm') {
        return this.send('audio_data', {
            call_id: callId,
            audio: audioBase64,
            format: format,
        });
    }

    /** 麦克风状态变更 */
    sendMicStatus(callId, muted) {
        return this.send('mic_status', {
            call_id: callId,
            muted: muted,
        });
    }

    /** 文字输入 */
    sendTextInput(callId, text) {
        return this.send('text_input', {
            call_id: callId,
            text: text,
        });
    }

    // ── 内部方法 ────────────────────────────────────

    _dispatch(type, payload) {
        const callbacks = this.handlers[type] || [];
        callbacks.forEach(cb => {
            try {
                cb(payload);
            } catch (e) {
                console.error(`[WS] 处理 ${type} 异常:`, e);
            }
        });
    }

    _tryReconnect() {
        if (this.reconnectCount >= MAX_RECONNECT) {
            console.error('[WS] 超过最大重连次数，停止重连');
            return;
        }
        this.reconnectCount++;
        console.log(`[WS] ${RECONNECT_DELAY/1000}s 后进行第 ${this.reconnectCount} 次重连...`);
        this._clearReconnect();
        this.reconnectTimer = setTimeout(() => this.connect(), RECONNECT_DELAY);
    }

    _clearReconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }
}

/** 全局单例 */
export const wsClient = new WsClient();
