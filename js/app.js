/**
 * VoiceCall WebUI - 主入口
 *
 * 整合所有模块，管理 DOM 交互和全局状态。
 */

import { wsClient } from './ws_client.js';
import { AudioManager } from './audio_manager.js';
import { CallState, CallStateManager } from './call_state.js';
import { SubtitlePanel } from './subtitle.js';

// ── DOM 元素引用 ────────────────────────────────────

const Elem = {
    body: document.body,
    container: document.getElementById('app-container'),

    // 屏幕
    homeScreen: document.getElementById('home-screen'),
    callScreen: document.getElementById('call-screen'),

    // 顶部栏
    themeToggle: document.getElementById('theme-toggle'),
    settingsButton: document.getElementById('settings-button'),
    wsIndicator: document.getElementById('ws-indicator'),

    // 主页按钮
    makeCallBtn: document.getElementById('make-call-btn'),
    // 通话界面
    callAvatar: document.getElementById('call-avatar'),
    callContainer: document.querySelector('.call-container'),
    callerNameDisplay: document.getElementById('caller-name-display'),
    callStatus: document.getElementById('call-status'),
    callTimer: document.getElementById('call-timer'),

    // 控制按钮
    incomingControls: document.getElementById('incoming-controls'),
    activeCallControls: document.getElementById('active-call-controls'),
    rejectCallBtn: document.getElementById('reject-call-btn'),
    answerCallBtn: document.getElementById('answer-call-btn'),
    micToggleBtn: document.getElementById('mic-toggle-btn'),
    hangupCallBtn: document.getElementById('hangup-call-btn'),
    speakerToggleBtn: document.getElementById('speaker-toggle-btn'),

    // 字幕面板
    subtitlePanel: document.getElementById('subtitle-panel'),

    // 文字输入（静音模式）
    textInputArea: document.getElementById('text-input-area'),
    textInput: document.getElementById('text-input'),
    textSendBtn: document.getElementById('text-send-btn'),

    // 设置弹窗
    settingsModal: document.getElementById('settings-modal'),
    closeModalBtn: document.getElementById('close-modal-btn'),
    saveSettingsBtn: document.getElementById('save-settings-btn'),
    resetSettingsBtn: document.getElementById('reset-settings-btn'),
    callerNameInput: document.getElementById('caller-name-input'),
    avatarUrlInput: document.getElementById('avatar-url'),
    avatarUpload: document.getElementById('avatar-upload'),
    bgUrlInput: document.getElementById('bg-url'),
    bgUpload: document.getElementById('bg-upload'),
    callUiStyleSelect: document.getElementById('call-ui-style'),
    subtitleToggle: document.getElementById('subtitle-toggle'),
    subtitleSettingHint: document.getElementById('subtitle-setting-hint'),
};

// ── 模块实例 ────────────────────────────────────────

const audioManager = new AudioManager();
const callState = new CallStateManager();
const subtitle = new SubtitlePanel(Elem.subtitlePanel);

// 常量
const defaultCallerName = 'AI 助手';
const appConfig = {
    showSubtitle: true,
    subtitleEnabled: true,
    textInputMode: true,
};
let keepPlaybackAfterEnd = false;

// ── 初始化 ──────────────────────────────────────────

function init() {
    loadSettings();
    bindUIEvents();
    bindCallStateEvents();
    bindAudioEvents();
    bindWsEvents();
    bindThemeEvents();

    // 连接 WebSocket
    wsClient.connect();

    // 手机浏览器可能在切回前台后暂停 WebSocket；恢复时主动补连。
    window.addEventListener('pageshow', () => {
        if (!wsClient.connected) wsClient.connect();
    });
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && !wsClient.connected) wsClient.connect();
    });

    // 在任意首次点击/触摸中提前解锁移动端播放权限。拨号与接听事件还会
    // 再次调用 prepareForCall()，因此这只是额外的兼容保障。
    const unlockOnFirstGesture = () => {
        void audioManager.unlockPlayback();
        document.removeEventListener('pointerdown', unlockOnFirstGesture);
        document.removeEventListener('touchstart', unlockOnFirstGesture);
    };
    document.addEventListener('pointerdown', unlockOnFirstGesture, { passive: true });
    document.addEventListener('touchstart', unlockOnFirstGesture, { passive: true });

    // 显示主页面
    showView(Elem.homeScreen);
}

// ── WebSocket 事件绑定 ──────────────────────────────

function bindWsEvents() {
    // 连接/断开
    wsClient.on('__connected__', () => {
        updateWsIndicator(true);
    });

    wsClient.on('__disconnected__', () => {
        updateWsIndicator(false);
    });

    // 插件配置
    wsClient.on('config', (payload) => {
        appConfig.showSubtitle = payload.show_subtitle !== false;
        appConfig.textInputMode = payload.text_input_mode !== false;
        syncSubtitleSettingControl();
        setSubtitleVisible(true);
        if (!appConfig.textInputMode) {
            Elem.textInputArea.style.display = 'none';
        }
    });

    // 来电通知
    wsClient.on('incoming_call', (payload) => {
        const { call_id, message } = payload;
        callState.setRinging(call_id, message);
    });

    // 通话状态更新（CALLING 阶段的反馈）
    wsClient.on('call_status', (payload) => {
        if (payload.status === 'calling') {
            if (callState.isIdle && payload.call_id) {
                callState.setCalling(payload.call_id);
            }
            Elem.callStatus.textContent = payload.message || '正在等待 AI 回应...';
        }
    });

    // 通话接通
    wsClient.on('call_connected', (payload) => {
        callState.setConnected(payload.call_id);
        addSystemSubtitle('通话已接通');
    });

    // 通话结束
    wsClient.on('call_ended', (payload) => {
        const reasonText = getEndReasonText(payload.reason);
        addSystemSubtitle(reasonText);
        audioManager.stopRecording();
        keepPlaybackAfterEnd = ['ai_hangup', 'rejected'].includes(payload.reason);
        if (!keepPlaybackAfterEnd) {
            audioManager.stopPlayback();
        }
        // 立即停止计时，但保留 1.5 秒展示结束原因
        callState.stopTimer();
        Elem.callTimer.style.display = 'none';
        Elem.callStatus.textContent = reasonText;
        Elem.callStatus.style.display = 'block';
        Elem.incomingControls.style.display = 'none';
        Elem.activeCallControls.style.display = 'none';
        Elem.textInputArea.style.display = 'none';
        setTimeout(() => {
            callState.setEnded(payload.reason || 'hangup');
        }, 1500);
    });

    // 播放音频
    wsClient.on('play_audio', async (payload) => {
        const { audio_data, format } = payload;
        if (audio_data) {
            await audioManager.playAudio(audio_data, format || 'mp3');
        }
        // 字幕由 subtitle 消息单独处理
    });

    // 字幕更新
    wsClient.on('subtitle', (payload) => {
        if (isSubtitleEnabled()) {
            subtitle.add(payload.speaker, payload.text);
        }
    });

    // 错误
    wsClient.on('error', (payload) => {
        console.error('[App] 服务器错误:', payload.message);
        showToast(payload.message || '发生错误', 'error');
    });
}

// ── 通话状态事件绑定 ────────────────────────────────

function bindCallStateEvents() {
    callState.onStateChange = (oldState, newState, data) => {
        console.log(`[App] UI 状态变更: ${oldState} → ${newState}`);

        switch (newState) {
            case CallState.CALLING:
                // 用户发起呼叫
                updateCallerInfo();
                showView(Elem.callScreen);
                Elem.callContainer.className = 'call-container calling';
                Elem.callStatus.innerHTML = '正在等待 AI 回应<span class="loading-dots"></span>';
                Elem.callStatus.style.display = 'block';
                Elem.callTimer.style.display = 'none';
                Elem.incomingControls.style.display = 'none';
                // 显示简化的挂断按钮（允许取消拨打）
                Elem.activeCallControls.style.display = 'grid';
                Elem.micToggleBtn.style.display = 'none';
                Elem.speakerToggleBtn.style.display = 'none';
                subtitle.clear();
                setSubtitleVisible(true);
                Elem.textInputArea.style.display = 'none';
                break;

            case CallState.RINGING:
                // AI 来电
                updateCallerInfo();
                showView(Elem.callScreen);
                Elem.callContainer.className = 'call-container ringing';
                Elem.answerCallBtn.disabled = false;
                Elem.rejectCallBtn.disabled = false;
                Elem.callStatus.textContent = data.message || '来电...';
                Elem.callStatus.style.display = 'block';
                Elem.callTimer.style.display = 'none';
                Elem.incomingControls.style.display = 'flex';
                Elem.activeCallControls.style.display = 'none';
                subtitle.clear();
                setSubtitleVisible(true);
                Elem.textInputArea.style.display = 'none';
                break;

            case CallState.CONNECTED:
                // 通话中
                updateCallerInfo();
                showView(Elem.callScreen);
                Elem.callContainer.className = 'call-container active-call';
                Elem.callStatus.style.display = 'none';
                Elem.callTimer.style.display = 'block';
                Elem.incomingControls.style.display = 'none';
                Elem.activeCallControls.style.display = 'grid';
                Elem.micToggleBtn.style.display = '';
                Elem.speakerToggleBtn.style.display = '';
                setSubtitleVisible(true);

                // 桌面端旧页面或重连恢复时补启；手机端通常已在点击接听/拨号时预授权。
                if (!audioManager.isMuted) {
                    void audioManager.startRecording();
                }
                resetMicButton();
                break;

            case CallState.IDLE:
                // 空闲
                if (Elem.callContainer) Elem.callContainer.className = 'call-container';
                audioManager.stopRecording();
                if (!keepPlaybackAfterEnd) {
                    audioManager.stopPlayback();
                }
                keepPlaybackAfterEnd = false;
                showView(Elem.homeScreen);
                Elem.textInputArea.style.display = 'none';
                break;
        }
    };

    callState.onTimerTick = (timeStr) => {
        Elem.callTimer.textContent = timeStr;
    };
}

// ── 音频事件绑定 ────────────────────────────────────

function bindAudioEvents() {
    audioManager.onAudioReady = (audioBase64, format) => {
        if (callState.isInCall && callState.callId) {
            wsClient.sendAudioData(callState.callId, audioBase64, format);
        }
    };

    audioManager.onError = (error) => {
        console.error('[App] 音频错误:', error);
        showToast(getAudioErrorMessage(error), 'error');
    };

    audioManager.onPlayStart = () => {
        if (audioManager.isRecording) {
            audioManager.pauseRecording();
        }
    };

    audioManager.onPlayEnd = () => {
        if (callState.isInCall && !audioManager.isMuted) {
            void audioManager.startRecording();
        }
    };
}

function getAudioErrorMessage(error) {
    const name = error?.name || '';
    const detail = String(error?.message || '').trim();
    if (name === 'SecurityError' || /HTTPS\/WSS/.test(detail)) {
        return '手机麦克风需要 HTTPS/WSS 网页，请按插件说明配置后重试。';
    }
    if (name === 'NotAllowedError') {
        return detail || '请允许浏览器使用麦克风，并点击接听开启声音。';
    }
    if (name === 'NotSupportedError') {
        return detail || '当前浏览器不支持此音频功能，请使用新版 Chrome 或 Safari。';
    }
    return detail || '音频初始化失败，请检查浏览器权限和系统媒体音量。';
}

// ── UI 事件绑定 ─────────────────────────────────────

function bindUIEvents() {
    // 主页按钮
    Elem.makeCallBtn.addEventListener('click', async () => {
        if (!wsClient.connected) {
            alert('未连接到服务，请确认插件已启动');
            return;
        }
        // 先在真实用户点击中申请权限；不要等到 call_connected 的异步 WS 回调。
        const preparation = audioManager.prepareForCall();
        wsClient.sendUserCall();
        await preparation;
    });

    // 通话按钮
    Elem.answerCallBtn.addEventListener('click', async () => {
        if (!wsClient.connected) {
            Elem.callStatus.textContent = '连接已断开，请稍候重试';
            return;
        }
        if (!callState.callId) {
            Elem.callStatus.textContent = '来电信息尚未就绪，请稍候重试';
            return;
        }
        // iOS / Android 需要在接听点击里预解锁扬声器和麦克风。
        const preparation = audioManager.prepareForCall();
        if (wsClient.sendAnswerCall(callState.callId)) {
            Elem.answerCallBtn.disabled = true;
            Elem.rejectCallBtn.disabled = true;
            Elem.callStatus.textContent = '正在接通...';
        }
        await preparation;
    });

    Elem.rejectCallBtn.addEventListener('click', () => {
        if (wsClient.connected && callState.callId) {
            wsClient.sendRejectCall(callState.callId);
        }
        callState.setEnded('user_rejected');
    });

    Elem.hangupCallBtn.addEventListener('click', () => {
        if (callState.state === CallState.CALLING) {
            // CALLING 状态：取消拨打
            if (wsClient.connected && callState.callId) {
                wsClient.sendHangup(callState.callId);
            }
            callState.setEnded('user_cancelled');
            return;
        }
        if (wsClient.connected && callState.callId) {
            wsClient.sendHangup(callState.callId);
        }
        callState.setEnded('user_hangup');
    });

    // 麦克风切换
    Elem.micToggleBtn.addEventListener('click', () => {
        void audioManager.unlockPlayback();
        const isMuted = audioManager.toggleMute();
        toggleIcon(Elem.micToggleBtn);

        // 通知插件麦克风状态
        if (wsClient.connected && callState.callId) {
            wsClient.sendMicStatus(callState.callId, isMuted);
        }

        // 显示/隐藏文字输入区域
        Elem.textInputArea.style.display = (isMuted && appConfig.textInputMode) ? 'flex' : 'none';
        if (isMuted && !appConfig.textInputMode) {
            showToast('文字输入模式未开启', 'info');
        }
    });

    // 扬声器切换
    Elem.speakerToggleBtn.addEventListener('click', () => {
        const enabled = audioManager.setSpeakerEnabled(!audioManager.speakerEnabled);
        toggleIcon(Elem.speakerToggleBtn);
        showToast(enabled ? '已开启网页声音' : '已关闭网页声音', 'info');
    });

    // 文字输入发送
    Elem.textSendBtn.addEventListener('click', () => {
        sendTextInput();
    });

    Elem.textInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendTextInput();
        }
    });

    // 设置弹窗（保留原有逻辑）
    bindSettingsEvents();
}

function bindSettingsEvents() {
    Elem.settingsButton.addEventListener('click', () => {
        Elem.settingsModal.style.display = 'flex';
    });

    Elem.closeModalBtn.addEventListener('click', () => {
        Elem.settingsModal.style.display = 'none';
    });

    window.addEventListener('click', (e) => {
        if (e.target === Elem.settingsModal) {
            Elem.settingsModal.style.display = 'none';
        }
    });

    Elem.saveSettingsBtn.addEventListener('click', saveSettings);
    Elem.resetSettingsBtn.addEventListener('click', resetSettings);
}

function bindThemeEvents() {
    Elem.themeToggle.addEventListener('click', () => {
        const currentTheme = Elem.body.getAttribute('data-theme');
        const newTheme = currentTheme === 'day' ? 'night' : 'day';
        Elem.body.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        // CSS 自动通过 .icon-sun::after 切换日/月图标
    });
}

// ── 文字输入 ────────────────────────────────────────

function sendTextInput() {
    const text = Elem.textInput.value.trim();
    if (!text) return;

    // 发送中禁用按钮
    Elem.textSendBtn.disabled = true;
    Elem.textInput.disabled = true;

    if (wsClient.connected && callState.callId) {
        wsClient.sendTextInput(callState.callId, text);
    }

    Elem.textInput.value = '';

    // 短暂延迟后恢复
    setTimeout(() => {
        Elem.textSendBtn.disabled = false;
        Elem.textInput.disabled = false;
        Elem.textInput.focus();
    }, 500);
}

// ── 视图切换 ────────────────────────────────────────

function showView(viewToShow) {
    document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
    viewToShow.classList.add('active');
}

// ── WS 连接状态指示器 ──────────────────────────────

function updateWsIndicator(connected) {
    if (Elem.wsIndicator) {
        if (connected) {
            Elem.wsIndicator.classList.add('online');
            Elem.wsIndicator.title = '已连接';
        } else {
            Elem.wsIndicator.classList.remove('online');
            Elem.wsIndicator.title = '未连接';
        }
    }
}

function setSubtitleVisible(visible) {
    subtitle.setVisible(Boolean(isSubtitleEnabled() && visible));
}

function addSystemSubtitle(text) {
    if (isSubtitleEnabled()) {
        subtitle.addSystem(text);
    }
}

function isSubtitleEnabled() {
    return Boolean(appConfig.showSubtitle && appConfig.subtitleEnabled);
}

function syncSubtitleSettingControl() {
    if (!Elem.subtitleToggle) return;
    Elem.subtitleToggle.checked = appConfig.subtitleEnabled;
    Elem.subtitleToggle.disabled = !appConfig.showSubtitle;
    if (Elem.subtitleSettingHint) {
        Elem.subtitleSettingHint.textContent = appConfig.showSubtitle
            ? '在本网页显示本次通话的双方字幕'
            : '字幕已被 AstrBot 插件后台关闭，无法在网页中开启';
    }
}

// ── 图标切换 ────────────────────────────────────────

function toggleIcon(button) {
    // 切换 toggled-off 类，CSS 自动处理图标变化
    button.classList.toggle('toggled-off');
}

function resetMicButton() {
    Elem.micToggleBtn.classList.remove('toggled-off');
}

// ── 来电信息更新 ────────────────────────────────────

function updateCallerInfo() {
    const callerName = localStorage.getItem('callerName') || defaultCallerName;
    Elem.callerNameDisplay.textContent = callerName;
}

// ── 设置管理 ────────────────────────────────────────

function loadSettings() {
    const savedTheme = localStorage.getItem('theme') || 'day';
    Elem.body.setAttribute('data-theme', savedTheme);
    // CSS .icon-sun::after 自动根据 data-theme 切换日/月图标

    const savedCallUiStyle = normalizeCallUiStyle(localStorage.getItem('callUiStyle') || 'default');
    applyCallUiStyle(savedCallUiStyle);
    if (Elem.callUiStyleSelect) {
        Elem.callUiStyleSelect.value = savedCallUiStyle;
    }

    appConfig.subtitleEnabled = localStorage.getItem('subtitleEnabled') !== 'false';
    syncSubtitleSettingControl();
    setSubtitleVisible(true);

    const savedName = localStorage.getItem('callerName') || '';
    Elem.callerNameInput.value = savedName;
    Elem.callerNameDisplay.textContent = savedName || defaultCallerName;

    const savedAvatar = localStorage.getItem('avatar') || '';
    if (savedAvatar) {
        Elem.callAvatar.style.backgroundImage = `url(${savedAvatar})`;
        Elem.callAvatar.textContent = '';
    }

    const savedBg = localStorage.getItem('background') || '';
    if (savedBg) {
        Elem.container.style.backgroundImage = `url(${savedBg})`;
    } else {
        Elem.container.style.backgroundImage = 'none';
    }
}

function saveSettings() {
    const callerName = Elem.callerNameInput.value.trim();
    localStorage.setItem('callerName', callerName);

    const callUiStyle = normalizeCallUiStyle(Elem.callUiStyleSelect?.value || 'default');
    localStorage.setItem('callUiStyle', callUiStyle);
    applyCallUiStyle(callUiStyle);

    if (Elem.subtitleToggle) {
        appConfig.subtitleEnabled = Elem.subtitleToggle.checked;
        localStorage.setItem('subtitleEnabled', String(appConfig.subtitleEnabled));
        setSubtitleVisible(true);
    }

    handleImageUpload(Elem.avatarUpload, Elem.avatarUrlInput, (src) => {
        if (src) {
            localStorage.setItem('avatar', src);
            Elem.callAvatar.style.backgroundImage = `url(${src})`;
            Elem.callAvatar.textContent = '';
        }
    });

    handleImageUpload(Elem.bgUpload, Elem.bgUrlInput, (src) => {
        if (src) {
            localStorage.setItem('background', src);
            Elem.container.style.backgroundImage = `url(${src})`;
        }
    });

    Elem.settingsModal.style.display = 'none';
    updateCallerInfo();
}

function resetSettings() {
    localStorage.removeItem('callerName');
    localStorage.removeItem('avatar');
    localStorage.removeItem('background');
    localStorage.removeItem('callUiStyle');
    localStorage.removeItem('subtitleEnabled');

    Elem.callerNameInput.value = '';
    Elem.avatarUrlInput.value = '';
    Elem.bgUrlInput.value = '';
    if (Elem.callUiStyleSelect) {
        Elem.callUiStyleSelect.value = 'default';
    }
    Elem.container.style.backgroundImage = 'none';

    loadSettings();
}

function normalizeCallUiStyle(style) {
    return ['default', 'qq', 'wechat'].includes(style) ? style : 'default';
}

function applyCallUiStyle(style) {
    Elem.body.setAttribute('data-call-ui', normalizeCallUiStyle(style));
}

function handleImageUpload(fileInput, urlInput, callback) {
    const file = fileInput.files[0];
    const url = urlInput.value.trim();

    if (file) {
        const reader = new FileReader();
        reader.onload = (e) => callback(e.target.result);
        reader.readAsDataURL(file);
        fileInput.value = '';
    } else if (url) {
        callback(url);
    }
}

// ── 挂断原因映射 ──────────────────────────────────

/**
 * 将插件返回的 reason 代码转为用户可读文本
 */
function getEndReasonText(reason) {
    const map = {
        'ai_hangup': 'AI 挂断了通话',
        'user_hangup': '你挂断了通话',
        'user_rejected': '你拒绝了来电',
        'user_cancelled': '你取消了拨打',
        'rejected': 'AI 拒绝了通话',
        'timeout': '呼叫超时，无人接听',
        'llm_error': 'AI 响应异常，通话取消',
        'no_command': 'AI 未响应，通话取消',
        'plugin_shutdown': '插件已关闭，通话中断',
    };
    return map[reason] || '通话已结束';
}

// ── Toast 通知 ──────────────────────────────────────

let toastContainer = null;

function getToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container';
        document.body.appendChild(toastContainer);
    }
    return toastContainer;
}

/**
 * 显示 Toast 通知
 * @param {string} message - 消息内容
 * @param {'error'|'info'|'success'} type - 类型
 */
function showToast(message, type = 'info') {
    const container = getToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    // 3 秒后自动移除
    setTimeout(() => {
        if (toast.parentNode) {
            toast.remove();
        }
    }, 3000);
}

// ── 启动 ────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);
