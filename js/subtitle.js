/**
 * VoiceCall WebUI - 字幕面板
 *
 * 通话过程中显示双方的对话记录。
 */

export class SubtitlePanel {
    constructor(containerEl) {
        this.container = containerEl;
        this.entries = [];
        this.maxEntries = 50;  // 最多保留条目数
    }

    /**
     * 添加一条字幕
     * @param {string} speaker - 'user' | 'ai' | 'system'
     * @param {string} text - 字幕文本
     */
    add(speaker, text) {
        if (!text) return;

        const entry = {
            speaker,
            text,
            time: new Date(),
        };
        this.entries.push(entry);

        // 超过上限时移除旧条目
        while (this.entries.length > this.maxEntries) {
            this.entries.shift();
        }

        this._renderEntry(entry);

        // 自动滚动到底部
        this.container.scrollTop = this.container.scrollHeight;
    }

    /**
     * 添加系统消息（通话状态变更等）
     * @param {string} text - 消息文本
     */
    addSystem(text) {
        this.add('system', text);
    }

    /**
     * 清空所有字幕
     */
    clear() {
        this.entries = [];
        this.container.innerHTML = '';
    }

    /**
     * 显示/隐藏面板
     */
    setVisible(visible) {
        this.container.style.display = visible ? 'flex' : 'none';
    }

    isVisible() {
        return this.container.style.display !== 'none';
    }

    // ── 内部 ────────────────────────────────────────

    _renderEntry(entry) {
        const div = document.createElement('div');
        div.className = `subtitle-entry subtitle-${entry.speaker}`;

        if (entry.speaker === 'system') {
            div.innerHTML = `<span class="subtitle-system-text">${this._escapeHtml(entry.text)}</span>`;
        } else {
            const speakerLabel = entry.speaker === 'ai' ? 'AI' : '你';
            const timeStr = entry.time.toLocaleTimeString('zh-CN', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            });
            div.innerHTML = `
                <span class="subtitle-speaker">${speakerLabel}</span>
                <span class="subtitle-text">${this._escapeHtml(entry.text)}</span>
                <span class="subtitle-time">${timeStr}</span>
            `;
        }

        this.container.appendChild(div);
    }

    _escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;',
        };
        return text.replace(/[&<>"']/g, c => map[c]);
    }
}
