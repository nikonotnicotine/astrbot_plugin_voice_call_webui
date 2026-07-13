/**
 * VoiceCall WebUI - 音频管理器
 *
 * 负责:
 * - 麦克风采集（getUserMedia + MediaRecorder）
 * - 音频播放（TTS 输出）
 * - Base64 编码/解码
 */

export class AudioManager {
    constructor() {
        this.mediaStream = null;       // getUserMedia stream
        this.mediaRecorder = null;     // MediaRecorder 实例
        this.audioChunks = [];         // 录制的音频块
        this.segmentMs = 3000;
        // Browsers may ignore capture-rate constraints. Always write a
        // deterministic 16 kHz PCM WAV for the local SenseVoice provider.
        this.targetSampleRate = 16000;
        this.segmentTimer = null;
        this.recordingContext = null;
        this.recordingSource = null;
        this.recordingProcessor = null;
        this.pcmChunks = [];
        this.pcmSampleCount = 0;
        this.minSpeechDurationMs = 700;
        this.minSpeechRms = 0.012;
        this.minSpeechPeak = 0.05;
        this.minVoicedRatio = 0.08;
        this.voicedFrameRms = 0.018;
        this.isRecording = false;
        this.isMuted = false;
        this._recordingStartPromise = null;

        // 手机浏览器只会在用户点击中允许解锁声音；必须长期复用播放对象，
        // 不能在 WebSocket 回调里临时创建 Audio 元素。
        this.audioContext = null;
        this.outputGain = null;
        this.currentBufferSource = null;
        this.currentAudio = typeof Audio === 'undefined' ? null : new Audio();
        this.currentObjectUrl = null;
        this.playbackUnlocked = false;
        this.playbackActive = false;
        this.speakerEnabled = true;
        this.pendingPlayback = null;
        this._playbackRequestId = 0;

        if (this.currentAudio) {
            this.currentAudio.preload = 'auto';
            this.currentAudio.playsInline = true;
            this.currentAudio.setAttribute('playsinline', '');
        }

        // 回调
        this.onAudioReady = null;      // (base64Audio, format) => void
        this.onPlayStart = null;       // () => void
        this.onPlayEnd = null;         // () => void
        this.onError = null;           // (error) => void
    }

    // ── 麦克风采集 ──────────────────────────────────

    /**
     * 请求麦克风权限并开始录音
     */
    async startRecording() {
        if (this.isRecording) return true;
        if (this._recordingStartPromise) return this._recordingStartPromise;

        this._recordingStartPromise = this._startRecordingInternal();
        try {
            return await this._recordingStartPromise;
        } finally {
            this._recordingStartPromise = null;
        }
    }

    async _startRecordingInternal() {
        try {
            this._assertMicrophoneAvailable();
            if (!this._hasLiveMicrophoneStream()) {
                this.mediaStream = await navigator.mediaDevices.getUserMedia({
                    audio: {
                        sampleRate: this.targetSampleRate,
                        channelCount: 1,
                        echoCancellation: true,
                        noiseSuppression: true,
                    }
                });
            }

            this.isRecording = true;
            this.isMuted = false;
            await this._startPcmRecorder();
            console.log('[Audio] 开始录音');
            return true;
        } catch (e) {
            console.error('[Audio] 无法启用麦克风:', e);
            this.isRecording = false;
            this._reportError(e);
            return false;
        }
    }

    /**
     * 停止录音
     */
    stopRecording() {
        this.pauseRecording();
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }
        console.log('[Audio] 停止录音并释放麦克风');
    }

    /**
     * 暂停录音但保留已授权的麦克风。AI 播报或临时静音时使用，
     * 这样手机不会在每次说话后重新申请权限。
     */
    pauseRecording() {
        if (!this.isRecording && !this.recordingContext && !this.mediaRecorder) return;

        this.isRecording = false;
        this._clearSegmentTimer();
        this._stopPcmRecorder(false);
        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            this.mediaRecorder.stop();
        }
        this.mediaRecorder = null;
        console.log('[Audio] 暂停录音');
    }

    /**
     * 切换静音状态
     * @returns {boolean} 新的静音状态
     */
    toggleMute() {
        if (this.isMuted) {
            this.isMuted = false;
            void this.startRecording();
        } else {
            this.isMuted = true;
            this.pauseRecording();
        }
        return this.isMuted;
    }

    /**
     * 必须从“拨号 / 接听”的用户点击中调用，预先解锁声音与麦克风。
     */
    async prepareForCall() {
        const [audioResult, micResult] = await Promise.allSettled([
            this.unlockPlayback(),
            this.startRecording(),
        ]);
        return {
            playbackReady: audioResult.status === 'fulfilled' && audioResult.value,
            microphoneReady: micResult.status === 'fulfilled' && micResult.value,
        };
    }

    // ── 音频播放 ────────────────────────────────────

    /**
     * 播放 Base64 编码的音频
     * @param {string} audioBase64 - Base64 音频数据
     * @param {string} format - 音频格式 (默认 mp3)
     */
    async playAudio(audioBase64, format = 'mp3') {
        if (!audioBase64) return false;
        if (!this.playbackUnlocked) {
            this.pendingPlayback = { audioBase64, format };
            this._reportError(this._audioError(
                '请先点击“拨号”或“接听”以开启手机声音，然后重试。',
                'NotAllowedError',
            ));
            return false;
        }

        const requestId = ++this._playbackRequestId;
        this.stopPlayback(false);
        try {
            const context = await this._getPlaybackContext();
            const arrayBuffer = this._base64ToArrayBuffer(audioBase64);
            const decoded = await context.decodeAudioData(arrayBuffer.slice(0));
            if (requestId !== this._playbackRequestId) return false;
            this._playAudioBuffer(context, decoded, requestId);
            return true;
        } catch (decodeError) {
            console.warn('[Audio] WebAudio 解码失败，使用 HTML 音频后备:', decodeError);
            return this._playHtmlAudio(audioBase64, format, requestId, decodeError);
        }
    }

    /**
     * 停止当前播放
     */
    stopPlayback(invalidate = true) {
        if (invalidate) this._playbackRequestId++;
        if (this.currentBufferSource) {
            try {
                this.currentBufferSource.stop();
            } catch (_) {
                // 已自然结束时 stop() 可能抛错，可忽略。
            }
            this.currentBufferSource.disconnect();
            this.currentBufferSource = null;
        }
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio.removeAttribute('src');
            this.currentAudio.load();
        }
        this._releaseObjectUrl();
        this.playbackActive = false;
    }

    /**
     * 是否正在播放
     */
    isPlaying() {
        return this.playbackActive;
    }

    /** 开关网页扬声器输出（浏览器不能强制选择实体扬声器）。 */
    setSpeakerEnabled(enabled) {
        this.speakerEnabled = Boolean(enabled);
        if (this.outputGain) this.outputGain.gain.value = this.speakerEnabled ? 1 : 0;
        if (this.currentAudio) this.currentAudio.muted = !this.speakerEnabled;
        return this.speakerEnabled;
    }

    // ── 释放资源 ────────────────────────────────────

    /**
     * 释放所有音频资源
     */
    dispose() {
        this.stopRecording();
        this.stopPlayback();
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
    }

    /**
     * 在用户手势中恢复 AudioContext 并播放无声帧，解锁移动浏览器媒体输出。
     */
    async unlockPlayback() {
        try {
            const context = await this._getPlaybackContext();
            if (context.state === 'suspended') {
                await context.resume();
            }
            const source = context.createBufferSource();
            source.buffer = context.createBuffer(1, 1, context.sampleRate || 22050);
            source.connect(this.outputGain || context.destination);
            source.start(0);
            this.playbackUnlocked = context.state === 'running';

            if (!this.playbackUnlocked) {
                throw this._audioError('浏览器未能开启声音，请再次点击接听或检查静音设置。', 'NotAllowedError');
            }

            if (this.pendingPlayback) {
                const pending = this.pendingPlayback;
                this.pendingPlayback = null;
                void this.playAudio(pending.audioBase64, pending.format);
            }
            return true;
        } catch (e) {
            this.playbackUnlocked = false;
            this._reportError(e);
            return false;
        }
    }

    // ── 内部方法 ────────────────────────────────────

    _assertMicrophoneAvailable() {
        const hostname = window.location.hostname;
        const localPage = hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
        if (!window.isSecureContext && !localPage) {
            throw this._audioError(
                '手机麦克风需要通过 HTTPS/WSS 访问通话网页；请按插件说明配置 HTTPS 后重试。',
                'SecurityError',
            );
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            throw this._audioError('当前浏览器不支持麦克风权限，请使用新版 Chrome、Safari 或系统浏览器。', 'NotSupportedError');
        }
    }

    _hasLiveMicrophoneStream() {
        return Boolean(this.mediaStream && this.mediaStream.getAudioTracks().some(track => track.readyState === 'live'));
    }

    async _getPlaybackContext() {
        if (!this.audioContext || this.audioContext.state === 'closed') {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (!AudioContextClass) {
                throw this._audioError('当前浏览器不支持网页音频播放。', 'NotSupportedError');
            }
            this.audioContext = new AudioContextClass();
            this.outputGain = this.audioContext.createGain();
            this.outputGain.gain.value = this.speakerEnabled ? 1 : 0;
            this.outputGain.connect(this.audioContext.destination);
        }
        return this.audioContext;
    }

    _playAudioBuffer(context, audioBuffer, requestId) {
        const source = context.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(this.outputGain || context.destination);
        source.onended = () => {
            if (this.currentBufferSource !== source || requestId !== this._playbackRequestId) return;
            this.currentBufferSource = null;
            this.playbackActive = false;
            if (this.onPlayEnd) this.onPlayEnd();
        };
        this.currentBufferSource = source;
        this.playbackActive = true;
        if (this.onPlayStart) this.onPlayStart();
        source.start(0);
    }

    async _playHtmlAudio(audioBase64, format, requestId, decodeError) {
        if (!this.currentAudio) {
            this._reportError(decodeError);
            return false;
        }
        try {
            const mimeType = this._formatToMime(format);
            const blob = new Blob([this._base64ToArrayBuffer(audioBase64)], { type: mimeType });
            this._releaseObjectUrl();
            this.currentObjectUrl = URL.createObjectURL(blob);
            const audio = this.currentAudio;
            audio.src = this.currentObjectUrl;
            audio.muted = !this.speakerEnabled;
            audio.onplay = () => {
                if (requestId !== this._playbackRequestId) return;
                this.playbackActive = true;
                if (this.onPlayStart) this.onPlayStart();
            };
            audio.onended = () => {
                if (requestId !== this._playbackRequestId) return;
                this.playbackActive = false;
                this._releaseObjectUrl();
                if (this.onPlayEnd) this.onPlayEnd();
            };
            audio.onerror = () => {
                if (requestId !== this._playbackRequestId) return;
                this.playbackActive = false;
                this._reportError(this._audioError('手机浏览器无法播放该音频格式，请更换 MP3、WAV 或 M4A TTS。', 'NotSupportedError'));
            };
            await audio.play();
            return true;
        } catch (e) {
            this.pendingPlayback = { audioBase64, format };
            this._reportError(e);
            return false;
        }
    }

    _formatToMime(format) {
        const value = String(format || 'mp3').toLowerCase();
        if (value === 'wav' || value === 'wave') return 'audio/wav';
        if (value === 'webm') return 'audio/webm';
        if (value === 'ogg' || value === 'opus') return 'audio/ogg';
        if (value === 'm4a' || value === 'mp4') return 'audio/mp4';
        if (value === 'aac') return 'audio/aac';
        return 'audio/mpeg';
    }

    _base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        return bytes.buffer;
    }

    _releaseObjectUrl() {
        if (this.currentObjectUrl) {
            URL.revokeObjectURL(this.currentObjectUrl);
            this.currentObjectUrl = null;
        }
    }

    _audioError(message, name = 'AudioError') {
        const error = new Error(message);
        error.name = name;
        return error;
    }

    _reportError(error) {
        if (this.onError) this.onError(error);
    }

    async _startPcmRecorder() {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) {
            console.warn('[Audio] WebAudio 不可用，回退到 MediaRecorder');
            this._startSegmentRecorder();
            return;
        }

        this.recordingContext = new AudioContextClass({ sampleRate: this.targetSampleRate });
        if (this.recordingContext.state === 'suspended') {
            await this.recordingContext.resume();
        }

        this.pcmChunks = [];
        this.pcmSampleCount = 0;
        this.recordingSource = this.recordingContext.createMediaStreamSource(this.mediaStream);
        this.recordingProcessor = this.recordingContext.createScriptProcessor(4096, 1, 1);

        this.recordingProcessor.onaudioprocess = (event) => {
            if (!this.isRecording || this.isMuted) return;

            const input = event.inputBuffer.getChannelData(0);
            const copy = new Float32Array(input.length);
            copy.set(input);
            this.pcmChunks.push(copy);
            this.pcmSampleCount += copy.length;

            const output = event.outputBuffer.getChannelData(0);
            output.fill(0);

            const sampleRate = this.recordingContext?.sampleRate || this.targetSampleRate;
            if (this.pcmSampleCount >= sampleRate * (this.segmentMs / 1000)) {
                this._flushPcmAudioSegment();
            }
        };

        this.recordingSource.connect(this.recordingProcessor);
        this.recordingProcessor.connect(this.recordingContext.destination);
        console.log(`[Audio] PCM/WAV 录音已启动 sampleRate=${this.recordingContext.sampleRate}`);
    }

    _stopPcmRecorder(flush = true) {
        if (flush) {
            this._flushPcmAudioSegment();
        } else {
            this.pcmChunks = [];
            this.pcmSampleCount = 0;
        }

        if (this.recordingProcessor) {
            this.recordingProcessor.disconnect();
            this.recordingProcessor.onaudioprocess = null;
            this.recordingProcessor = null;
        }
        if (this.recordingSource) {
            this.recordingSource.disconnect();
            this.recordingSource = null;
        }
        if (this.recordingContext) {
            this.recordingContext.close();
            this.recordingContext = null;
        }
    }

    _flushPcmAudioSegment() {
        if (!this.pcmChunks.length) return;

        const sourceSampleRate = this.recordingContext?.sampleRate || this.targetSampleRate;
        const sampleCount = this.pcmSampleCount;
        const chunks = this.pcmChunks;
        this.pcmChunks = [];
        this.pcmSampleCount = 0;

        if (sampleCount < sourceSampleRate * 0.5) return;

        const samples = new Float32Array(sampleCount);
        let offset = 0;
        for (const chunk of chunks) {
            samples.set(chunk, offset);
            offset += chunk.length;
        }

        const outputSamples = sourceSampleRate === this.targetSampleRate
            ? samples
            : this._resamplePcm(samples, sourceSampleRate, this.targetSampleRate);
        const speechStats = this._speechStats(outputSamples, this.targetSampleRate);
        if (!this._isLikelySpeech(speechStats)) {
            console.debug(
                `[Audio] 跳过静音/噪声音频段 duration=${speechStats.duration.toFixed(2)}s rms=${speechStats.rms.toFixed(4)} peak=${speechStats.peak.toFixed(4)} voiced=${speechStats.voicedRatio.toFixed(2)}`
            );
            return;
        }

        const wavBlob = this._encodeWav(outputSamples, this.targetSampleRate);
        console.debug(`[Audio] 发送 WAV 音频段 size=${wavBlob.size} duration=${(outputSamples.length / this.targetSampleRate).toFixed(2)}s inputRate=${sourceSampleRate} outputRate=${this.targetSampleRate}`);
        this._emitAudioBlob(wavBlob, 'audio/wav');
    }

    _resamplePcm(samples, inputRate, outputRate) {
        if (!samples.length || !inputRate || !outputRate || inputRate === outputRate) {
            return samples;
        }

        const outputLength = Math.max(1, Math.round(samples.length * outputRate / inputRate));
        const result = new Float32Array(outputLength);
        const ratio = inputRate / outputRate;
        for (let index = 0; index < outputLength; index++) {
            const position = index * ratio;
            const left = Math.min(Math.floor(position), samples.length - 1);
            const right = Math.min(left + 1, samples.length - 1);
            const fraction = position - left;
            result[index] = samples[left] + (samples[right] - samples[left]) * fraction;
        }
        return result;
    }

    _speechStats(samples, sampleRate) {
        if (!samples.length || !sampleRate) {
            return { duration: 0, rms: 0, peak: 0, voicedRatio: 0 };
        }

        let sumSquares = 0;
        let peak = 0;
        for (let i = 0; i < samples.length; i++) {
            const abs = Math.abs(samples[i]);
            if (abs > peak) peak = abs;
            sumSquares += samples[i] * samples[i];
        }

        const frameSize = Math.max(1, Math.floor(sampleRate * 0.02));
        let frameCount = 0;
        let voicedFrames = 0;
        for (let start = 0; start < samples.length; start += frameSize) {
            const end = Math.min(samples.length, start + frameSize);
            let frameSquares = 0;
            for (let i = start; i < end; i++) {
                frameSquares += samples[i] * samples[i];
            }
            const frameRms = Math.sqrt(frameSquares / Math.max(1, end - start));
            if (frameRms >= this.voicedFrameRms) voicedFrames++;
            frameCount++;
        }

        return {
            duration: samples.length / sampleRate,
            rms: Math.sqrt(sumSquares / samples.length),
            peak,
            voicedRatio: frameCount ? voicedFrames / frameCount : 0,
        };
    }

    _isLikelySpeech(stats) {
        return stats.duration * 1000 >= this.minSpeechDurationMs &&
            stats.rms >= this.minSpeechRms &&
            stats.peak >= this.minSpeechPeak &&
            stats.voicedRatio >= this.minVoicedRatio;
    }

    _encodeWav(samples, sampleRate) {
        const bytesPerSample = 2;
        const numChannels = 1;
        const dataSize = samples.length * bytesPerSample;
        const buffer = new ArrayBuffer(44 + dataSize);
        const view = new DataView(buffer);

        this._writeAscii(view, 0, 'RIFF');
        view.setUint32(4, 36 + dataSize, true);
        this._writeAscii(view, 8, 'WAVE');
        this._writeAscii(view, 12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, numChannels, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * numChannels * bytesPerSample, true);
        view.setUint16(32, numChannels * bytesPerSample, true);
        view.setUint16(34, 16, true);
        this._writeAscii(view, 36, 'data');
        view.setUint32(40, dataSize, true);

        let offset = 44;
        for (let i = 0; i < samples.length; i++) {
            const s = Math.max(-1, Math.min(1, samples[i]));
            view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
            offset += 2;
        }

        return new Blob([buffer], { type: 'audio/wav' });
    }

    _writeAscii(view, offset, text) {
        for (let i = 0; i < text.length; i++) {
            view.setUint8(offset + i, text.charCodeAt(i));
        }
    }

    _getSupportedMimeType() {
        const types = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/wav',
        ];
        for (const type of types) {
            if (MediaRecorder.isTypeSupported(type)) {
                return type;
            }
        }
        return 'audio/webm'; // fallback
    }

    _clearSegmentTimer() {
        if (this.segmentTimer) {
            clearTimeout(this.segmentTimer);
            this.segmentTimer = null;
        }
    }

    _startSegmentRecorder() {
        if (!this.isRecording || this.isMuted || !this.mediaStream) return;

        const mimeType = this._getSupportedMimeType();
        const chunks = [];

        try {
            this.mediaRecorder = new MediaRecorder(this.mediaStream, { mimeType });
        } catch (e) {
            console.error('[Audio] MediaRecorder 创建失败:', e);
            if (this.onError) this.onError(e);
            return;
        }

        this.mediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0) {
                chunks.push(event.data);
            }
        };

        this.mediaRecorder.onstop = async () => {
            this._clearSegmentTimer();

            const size = chunks.reduce((total, chunk) => total + chunk.size, 0);
            if (this.isRecording && !this.isMuted && size >= 1000) {
                await this._emitAudioBlob(new Blob(chunks, { type: mimeType }), mimeType);
            }

            if (this.isRecording && !this.isMuted && this.mediaStream) {
                setTimeout(() => this._startSegmentRecorder(), 0);
            }
        };

        this.mediaRecorder.start();
        this.segmentTimer = setTimeout(() => {
            if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
                this.mediaRecorder.stop();
            }
        }, this.segmentMs);
    }

    _blobToBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => {
                // data:audio/webm;base64,xxxx → 去掉前缀
                const result = reader.result;
                const base64 = result.split(',')[1];
                resolve(base64);
            };
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
    }

    async _emitAudioBlob(blob, mimeType) {
        try {
            const base64 = await this._blobToBase64(blob);
            const format = mimeType.includes('webm') ? 'webm' :
                           mimeType.includes('ogg') ? 'ogg' :
                           'wav';
            if (this.onAudioReady) {
                this.onAudioReady(base64, format);
            }
        } catch (e) {
            console.error('[Audio] Base64 转换失败:', e);
            if (this.onError) this.onError(e);
        }
    }
}
