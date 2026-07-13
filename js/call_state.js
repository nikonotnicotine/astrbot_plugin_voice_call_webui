/**
 * VoiceCall WebUI - 通话状态管理
 *
 * 前端状态机，与插件状态保持同步。
 * 管理 UI 视图切换和按钮状态。
 */

// 状态枚举
export const CallState = Object.freeze({
    IDLE: 'idle',
    CALLING: 'calling',       // 用户发起呼叫，等待 LLM 回应
    RINGING: 'ringing',       // AI 发起呼叫，等待用户接听
    CONNECTED: 'connected',   // 通话中
});

export class CallStateManager {
    constructor() {
        this._state = CallState.IDLE;
        this._callId = null;
        this._direction = null;  // 'incoming' | 'outgoing'

        // 回调
        this.onStateChange = null;  // (oldState, newState, data) => void
        this.onTimerTick = null;    // (timeStr) => void
        this._timerInterval = null;
        this._seconds = 0;
    }

    // ── 属性 ────────────────────────────────────────

    get state() { return this._state; }
    get callId() { return this._callId; }
    get direction() { return this._direction; }
    get isIdle() { return this._state === CallState.IDLE; }
    get isInCall() { return this._state === CallState.CONNECTED; }

    // ── 状态转换（由 WS 消息驱动）───────────────────

    /**
     * 用户点击拨号 → CALLING
     */
    setCalling(callId) {
        this._callId = callId || null;
        this._direction = 'outgoing';
        this._transition(CallState.CALLING, {
            callId: this._callId,
            direction: this._direction,
        });
    }

    /**
     * 收到来电 → RINGING
     */
    setRinging(callId, message = '') {
        // Keep the server-issued id before the UI is rendered.  The answer
        // button must send this exact id back to the WebSocket server.
        this._callId = callId || null;
        this._direction = 'incoming';
        this._transition(CallState.RINGING, {
            callId: this._callId,
            direction: this._direction,
            message: message,
        });
    }

    /**
     * 通话接通 → CONNECTED
     */
    setConnected(callId) {
        this._callId = callId;
        this._transition(CallState.CONNECTED, {
            callId: callId,
            direction: this._direction,
        });
        this._startTimer();
    }

    /**
     * 通话结束 → IDLE
     */
    setEnded(reason = 'hangup') {
        this._stopTimer();
        this._transition(CallState.IDLE, { reason });
        this._callId = null;
        this._direction = null;
    }

    /**
     * 强制重置
     */
    reset() {
        this._stopTimer();
        this._state = CallState.IDLE;
        this._callId = null;
        this._direction = null;
        this._seconds = 0;
    }

    // ── 计时器 ──────────────────────────────────────

    /** 公开的停止计时器方法 */
    stopTimer() {
        this._stopTimer();
    }

    _startTimer() {
        this._stopTimer();
        this._seconds = 0;
        if (this.onTimerTick) this.onTimerTick('00:00');
        this._timerInterval = setInterval(() => {
            this._seconds++;
            const mins = Math.floor(this._seconds / 60).toString().padStart(2, '0');
            const secs = (this._seconds % 60).toString().padStart(2, '0');
            if (this.onTimerTick) this.onTimerTick(`${mins}:${secs}`);
        }, 1000);
    }

    _stopTimer() {
        if (this._timerInterval) {
            clearInterval(this._timerInterval);
            this._timerInterval = null;
        }
    }

    _transition(newState, data = {}) {
        const oldState = this._state;
        this._state = newState;
        console.log(`[CallState] ${oldState} → ${newState}`, data);
        if (this.onStateChange) {
            this.onStateChange(oldState, newState, data);
        }
    }

    // ── 释放 ────────────────────────────────────────

    dispose() {
        this._stopTimer();
    }
}
