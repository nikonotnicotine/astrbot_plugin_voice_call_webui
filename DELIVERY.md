# 网页语音通话插件交付说明

## 本次交付内容

这是一个配合 AstrBot 使用的网页语音通话插件。QQ / NapCat 继续承担文字聊天；用户通过浏览器进入电话页面，即可与 AI 进行语音通话。

已包含的主要能力：

- 用户可从网页向 AI 发起电话，AI 可按人设接听或拒绝；
- AI 可主动发起来电，网页会显示来电状态；
- AI 主动来电时，可通知插件配置中指定的 QQ、群或会话；
- 可指定一个 QQ、群或 AstrBot 会话作为通话上下文，通话会读取该会话的人设、聊天记录和 Provider，并把新的通话内容写回该会话；
- 支持“用户语音 → 语音识别 → AstrBot AI → 语音合成 → 网页播放”；
- 支持字幕、静音后文字输入，以及默认 / QQ 电话 / 微信电话三种界面；
- 支持 OpenAI 兼容 STT，也支持本机 SenseVoice；
- 网页与 WebSocket 均支持访问密码保护。

## 手机、局域网与公网使用

本插件可供手机浏览器使用。手机正式进行语音通话时，推荐使用 **HTTPS 页面 + WSS WebSocket**；这样浏览器才能稳定允许麦克风和音频播放。

### 同一 Wi-Fi 临时测试

1. 电脑和手机连接同一个普通 Wi-Fi（访客 Wi-Fi、AP 隔离或 VPN 可能阻断访问）。
2. 在电脑运行 `ipconfig`，记下 IPv4 地址，例如 `192.168.1.23`。
3. 在 AstrBot 插件设置中填写：

   ```text
   webui_host = 0.0.0.0
   webui_port = 6888
   webui_public_url = http://192.168.1.23:6888/
   webui_password = 至少 16 位的强密码
   ```

4. Windows 防火墙仅对“专用网络”放行 TCP 6888 后，用手机打开 `http://192.168.1.23:6888/`。

`127.0.0.1` 只代表当前设备本身，手机不能用它访问电脑。局域网 HTTP 适合作连通性测试；部分手机浏览器会因安全策略拒绝其麦克风权限，因此正式手机通话应使用下方 HTTPS 方式。

### 正式手机 / 公网部署（推荐）

在有域名的电脑或 VPS 上使用 Caddy / Nginx 反向代理。插件保持本机监听，不暴露 6888：

```text
webui_host = 127.0.0.1
webui_port = 6888
webui_public_url = https://voice.example.com/
webui_password = 至少 16 位的强密码
```

将域名指向服务器，公网只开放 80/443，不开放 6888。最简 Caddy 配置：

```caddyfile
voice.example.com {
    reverse_proxy 127.0.0.1:6888
}
```

Caddy 会自动配置 HTTPS，并转发 WebSocket；手机访问 `https://voice.example.com/` 后，网页会自动连接 `wss://voice.example.com/ws`。完整 Nginx 配置、Windows 防火墙命令、手机权限排错见同目录的 [README.md](README.md)。

手机首次使用必须在页面上实际点击“接听”或“拨号”，并在浏览器弹窗中允许麦克风。若无声音，请检查手机媒体音量、静音模式、蓝牙音频输出和浏览器网站权限。

## 安装方式

1. 解压后，将整个 `voice_call_webui` 文件夹复制到 AstrBot 的插件目录：

   ```text
   C:\\Users\\<用户名>\\.astrbot_launcher\\instances\\<实例ID>\\core\\data\\plugins\\
   ```

2. 若 AstrBot 环境缺少 `aiohttp`，在该实例的 Python 环境安装：

   ```powershell
   <AstrBot实例目录>\\venv\\Scripts\\pip.exe install aiohttp
   ```

3. 重启 AstrBot，在插件配置中完成 STT、TTS、网页访问地址和密码设置。

4. 默认从本机浏览器打开：

   ```text
   http://127.0.0.1:6888/
   ```

完整的配置说明、Prompt、SenseVoice 配置和常见问题请见同目录的 [README.md](README.md)。

## 交付后必须配置

- `webui_password`：默认值为 `voicecall`。对外使用、VPS 或局域网部署时，请立即改为强密码。
- `webui_host`：本机使用 `127.0.0.1`；仅局域网测试时改为 `0.0.0.0`，并设置正确的 `webui_public_url`。通过 Caddy/Nginx 供手机或公网正式使用时，仍保持 `127.0.0.1`。
- `openai_stt_*`：填写客户自己的 OpenAI 兼容语音识别服务信息；本交付包不包含任何 API Key。
- `conversation_context_target`：填写目标 QQ、`group:群号` 或完整 UMO，即可固定读取该会话的上下文。
- `ai_call_notify_target`：填写需要接收 AI 来电通知的 QQ、`group:群号` 或完整 UMO。

## 安全与隐私

本交付包未包含 API Key、QQ Cookie、聊天记录、日志、录音、数据库或运行时缓存。运行后产生的 `data`、日志、临时音频及 `__pycache__` 不需要再次对外发送。

不要将网页地址和访问密码同时公开，也不要把 TCP 6888 直接映射到公网。网页密码不能替代 HTTPS、反向代理和防火墙；公网部署应只开放 443（申请 HTTPS 证书时另需 80）。通话音频会发送给客户自行配置的 STT 服务，指定上下文功能会读取并写回对应 QQ/群的 AstrBot 会话，因此请仅授权可信用户使用。
