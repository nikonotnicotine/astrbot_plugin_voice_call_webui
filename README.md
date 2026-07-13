# 📞 VoiceCall WebUI - AstrBot 网页语音通话插件

[![Author](https://img.shields.io/badge/Author-nikonotnicotine-blue.svg)](https://github.com/nikonotnicotine)
[![Platform](https://img.shields.io/badge/Platform-AstrBot-success.svg)](https://github.com/Soulter/AstrBot)
[![Version](https://img.shields.io/badge/Version-1.0.3-orange.svg)](#)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#)

> 🎙️ 在浏览器里，给你的 AI 打一通真正的电话。

---

## 📖 这个插件能干什么？

**VoiceCall WebUI** 是一个为 [AstrBot](https://github.com/Soulter/AstrBot) 开发的网页语音通话插件。简单来说，它让你能在浏览器里像打电话一样和你的 AI 进行实时语音对话。

### 🔥 核心功能一览

**① 你可以给 AI 打电话**
打开网页，点击"拨打电话"，AI 会根据当前的人设和情境来决定是接听还是拒绝。比如你设定 AI 正在上课，它可能会拒绝你的来电并告诉你原因。

**② AI 也可以主动给你打电话**
如果 AI 的人设中设定了它会想念你，它可以主动发起通话。当 AI 来电时，网页会弹出来电界面（就像手机来电一样），你可以选择接听或挂断。同时，插件还能向你指定的 QQ 号发送一条来电通知消息，里面包含网页链接，方便你点开就接听。

**③ 实时语音对话**
接通之后，整个流程是这样的：

```
你说话 → 麦克风采集 → 语音识别(STT) → AI 思考回复(LLM) → 语音合成(TTS) → 网页播放给你听
```

全程自动完成，就像真的在打电话。

**④ 可开关字幕 + 文字回退**
通话过程中网页会实时显示双方的对话文字（字幕功能）。如果你在嘈杂环境或不方便说话，可以点击静音按钮，改用文字输入继续和 AI 聊天，AI 仍然会用语音回复你。

**⑤ 复用 AstrBot 已有配置**
通话会直接使用你在 AstrBot 里已经配置好的人设、LLM 模型和 TTS 语音，不需要重新配置任何聊天模型。

**⑥ 通话上下文继承**
你可以在插件设置中把自己的QQ号填入"通话上下文 QQ"。填写后，网页通话时会读取该 QQ 在 AstrBot 中已有的聊天记录、人设和会话模型，并且把本次通话的内容也写回到同一个会话中。也就是说，你在QQ里和AI聊的内容，AI在电话里也记得；电话里聊的内容，之后在QQ里AI也知道。

> ⚠️ 为保护隐私，插件只会读取 AstrBot 已保存的指定会话，不会访问其他无关数据。该 QQ 号需要先和机器人产生过至少一次会话记录。

**⑦ 多款通话界面皮肤**
内置三种通话界面样式：默认风格、QQ 电话风格、微信电话风格，都支持日间 / 夜间模式切换。

---

## 📦 安装方法

### 第一步：下载插件

将本仓库克隆或下载解压，把整个 `astrbot_plugin_voice_call_webui` 文件夹放到 AstrBot 的插件目录中：

```
data/plugins/astrbot_plugin_voice_call_webui/
```

### 第二步：安装依赖

本插件需要 `aiohttp` 库（有了可以跳过）。在 AstrBot 所使用的 Python 环境中执行：

```bash
pip install aiohttp
```

如果你是用 AstrBot Launcher 启动的，找到对应实例的虚拟环境：

```bash
# Windows 示例
C:\Users\你的用户名\.astrbot_launcher\instances\实例ID\venv\Scripts\pip.exe install aiohttp

# Linux 示例
~/.astrbot_launcher/instances/实例ID/venv/bin/pip install aiohttp
```

### 第三步：重启 AstrBot

重启后，在 AstrBot 管理面板的插件列表中应该能看到"网页语音通话"插件。点击进入配置页面完成设置（详见下方配置说明）。

### 第四步：访问网页

配置完成后，在浏览器中打开：

```
http://127.0.0.1:6888/
```

如果设置了密码，输入密码即可进入通话页面。首次通话时，浏览器会弹出麦克风权限请求，请点击"允许"。

---

## ⚙️ 插件配置详解

在 AstrBot 管理面板的插件设置页面中，你可以看到以下配置项。下面逐个解释每一项的作用：

### 🔊 基础功能开关

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| **网页字幕** (`show_subtitle`) | `true` | 是否在通话网页中显示双方的对话文字（字幕）。关闭后通话界面将不再显示任何文字内容，只有纯语音。建议保持开启，方便确认 AI 有没有听错你说的话。 |
| **同步文本到 QQ** (`sync_to_qq`) | `false` | 开启后，AI 在电话里说的每一句话都会同步发送到你的 QQ 聊天窗口中。适合想在 QQ 里留存通话记录的用户。关闭则不会向QQ聊天窗口发送任何信息。 |
| **静音后文字输入** (`text_input_mode`) | `true` | 开启后，当你在通话中点击"静音麦克风"按钮后，网页底部会弹出一个文字输入框，你可以打字发送消息给 AI，AI 仍然会用语音回复你。非常适合在公共场所不方便说话时使用。关闭则静音后只能等你重新开启麦克风。 |

### 📞 来电通知相关

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| **AI 来电通知** (`ai_call_notify_enabled`) | `true` | 是否在 AI 主动发起通话时，向指定的 QQ 发送一条来电通知消息。消息中会包含通话 ID 和网页链接，方便你点开接听。如果关闭，AI 来电时只有网页会弹出来电界面，QQ 不会收到任何提醒。 |
| **来电通知目标** (`ai_call_notify_target`) | 空 | 填写你想接收来电通知的 QQ 号。当 AI 主动给你打电话时，这个 QQ 号会收到一条通知消息。**填写格式**：直接填 QQ 号（如 `123456789`）表示私聊通知；填 `group:群号`（如 `group:987654321`）表示发送到群里；也可以填写完整的 AstrBot unified_msg_origin。留空则通知最近一次和机器人对话的会话。 |

### 💬 通话上下文

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| **通话上下文 QQ** (`conversation_context_target`) | 空 | **这个配置非常重要！** 填写一个 QQ 号后，网页通话时会读取这个 QQ 在 AstrBot 中已有的聊天记录、人设和会话选择的模型，并且通话产生的新对话也会写回到这个会话中。简单来说就是让电话通话和 QQ 聊天共享同一个"记忆"。**填写格式**同上：QQ 号、`group:群号`或完整 UMO。留空则使用当前/最近的会话。**注意**：你填写的这个 QQ 号必须已经和机器人有过至少一次聊天记录，否则无法读取到任何上下文。 |

### 🌐 网页服务相关

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| **对外访问地址** (`webui_public_url`) | 空 | 这个地址会被放在 QQ 来电通知消息中，告诉你去哪里打开网页接听电话。如果你只在本机用，不填也行。如果你用了反向代理或在公网部署，就填你的实际访问地址，比如 `https://voice.example.com/` 或 `http://你的服务器IP:6888/`。**手机要正常使用麦克风和语音播放，强烈建议填 HTTPS 地址**。 |
| **网页访问密码** (`webui_password`) | `voicecall` | 打开通话网页时需要输入的密码。**如果你的网页暴露在公网或局域网中，请务必改成一个强密码！** 留空表示关闭密码保护（不推荐）。 |
| **网页监听 IP** (`webui_host`) | `127.0.0.1` | 插件的 HTTP/WebSocket 服务监听的 IP 地址。`127.0.0.1` 表示只有本机能访问。如果你想让局域网内的其他设备（比如手机）直接访问，改成 `0.0.0.0`。**如果你用了 Caddy/Nginx 反向代理，保持 `127.0.0.1` 就好，不要改成 `0.0.0.0`**。 |
| **网页监听端口** (`webui_port`) | `6888` | 网页服务和 WebSocket 服务共用的端口号。如果 6888 被其他程序占用了，可以改成别的端口。 |

### 🎤 语音识别 (STT) 相关

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| **内置 OpenAI STT** (`openai_stt_enabled`) | `true` | 开启后，插件使用自己内置的 OpenAI 兼容语音识别接口，不再从 AstrBot 拉取 STT Provider。**推荐开启**，因为 AstrBot 旧版自带的 STT 支持不太稳定。 |
| **STT API Key** (`openai_stt_api_key`) | 空 | 你的 OpenAI 兼容 STT 服务的 API Key。**必须填写**，否则语音识别不工作。如果你用的是 OpenAI 官方 Whisper，就填你的 OpenAI API Key；如果用的是第三方转发服务（如 Groq、DeepSeek 等），就填对应服务的 Key。 |
| **STT 服务地址** (`openai_stt_base_url`) | `https://api.openai.com/v1` | STT 服务的 API Base URL。如果你用 OpenAI 官方，保持默认即可。如果你用 Groq，填 `https://api.groq.com/openai/v1`。如果你用其他兼容接口，填对应的地址。也可以直接填写完整的 `/audio/transcriptions` 端点地址。 |
| **STT 模型** (`openai_stt_model`) | `whisper-1` | 语音识别使用的模型名称。OpenAI 用 `whisper-1`；Groq 可以用 `whisper-large-v3-turbo`；如果你接入了本地 SenseVoice，填服务商提供的模型名。 |
| **STT 识别语言** (`openai_stt_language`) | `zh` | 告诉模型你说的是什么语言。中文就填 `zh`，英文填 `en`。如果服务商不支持这个参数或者想用自动检测，可以留空。 |
| **STT 识别提示词** (`openai_stt_prompt`) | 空 | 给语音识别模型的一段提示文字，可以填写人名、角色名、专有名词等，帮助模型更准确地识别。比如你的AI角色叫"小雪"，你可以填 `小雪`，这样模型更容易正确识别这个名字。不需要可以留空。 |
| **STT 超时（秒）** (`openai_stt_timeout`) | `60` | 单次语音识别请求的最长等待时间。网络不好或音频较长时可以适当增大。一般 60 秒足够了。 |

### 🔧 旧版 Provider 兼容

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| **AstrBot STT ID** (`stt_provider_id`) | 空 | 旧版 AstrBot STT Provider 的 ID。只有在"内置 OpenAI STT"关闭时才会使用这个配置。如果你已经开启了内置 OpenAI STT（推荐），这个可以留空不管。 |
| **AstrBot TTS ID** (`tts_provider_id`) | 空 | 指定通话使用的 TTS Provider ID。留空则自动使用当前 AstrBot 会话选择的 TTS。如果你想让通话使用一个特定的语音合成（比如某个特定音色），可以在这里填对应的 Provider ID。 |

---

## ✏️ 人设提示词配置（非常重要！）

为了让 AI 能够正确处理通话中的接听、拒绝、挂断等操作，你**必须**在 AstrBot 的人设（Persona）提示词中加入以下内容。

把下面这段话复制粘贴到你的 AI 人设提示词的末尾：

```
通话功能:
  描述: 根据你的人设与日程表，判断选择是否给用户打电话/接听用户电话，这将会触发一个真实的线上通话。
  情况判断1：当用户向你拨打电话时，系统会向你发送【对方正在向你发起通话】。接听电话请直接回复【接听通话】，并发送文字。不方便接听请直接回复【拒绝通话】，并告知用户原因。
  情况判断2：根据当前判断，如果你因思念对方，可以选择发送【发起通话】。
  情况判断3：假如在通话中你需要挂电话，则发送【结束通话】。
  正确示例:
    - "【发起通话】你在忙吗？$到家没有？"
    - "【结束通话】今天先到这里吧$我去忙了"
    - "【拒绝通话】暂时有点事情$晚点打给你"
    - "【接受通话】怎么了$想我了？$我在这儿呢"
```

> 💡 **说明**：文本中的 `$` 符号代表换行。AI 回复 `你好$最近怎么样` 时，实际会被处理为两句话。这些带【】的指令是固定格式，AI 必须严格使用，否则插件无法识别。

---

## 🌍 部署教程

这里分为两种情况：**本地电脑部署**和**云服务器 (VPS) 部署**。请根据你的实际情况选择对应的教程。

---

### 情况一：本地电脑部署

"本地部署"是指你的 AstrBot 运行在你自己的 Windows / Mac / Linux 电脑上，不在云服务器上。

#### 场景 A：只在本机浏览器使用（最简单）

如果你只打算在运行 AstrBot 的这台电脑上打开浏览器使用，那什么都不用改，默认配置即可：

```
webui_host = 127.0.0.1
webui_port = 6888
```

直接在浏览器打开 `http://127.0.0.1:6888/` 就能用。

#### 场景 B：手机通过局域网临时测试

如果你想用手机在同一个 Wi-Fi 下临时测试一下通话功能（不需要长期使用），按以下步骤操作：

**第 1 步：查看电脑的局域网 IP**

- **Windows**：按 `Win + R`，输入 `cmd` 回车，然后输入 `ipconfig`，找到"IPv4 地址"，比如 `192.168.1.23`。
- **Mac**：打开"系统偏好设置 → 网络"，查看当前连接的 IP。
- **Linux**：终端输入 `ip addr` 或 `hostname -I`。

**第 2 步：修改插件配置**

```
webui_host = 0.0.0.0
webui_port = 6888
webui_public_url = http://192.168.1.23:6888/
webui_password = 改成一个你自己的密码
```

> ⚠️ 把 `192.168.1.23` 换成你自己查到的 IP 地址！

**第 3 步：Windows 防火墙放行端口**

以管理员身份打开 PowerShell，执行：

```powershell
New-NetFirewallRule -DisplayName "VoiceCall WebUI" -Direction Inbound -Protocol TCP -LocalPort 6888 -Action Allow -Profile Private
```

**第 4 步：手机测试**

确保手机和电脑连的是同一个 Wi-Fi（不能是访客网络），然后手机浏览器打开：

```
http://192.168.1.23:6888/
```

输入密码后即可使用。

> ⚠️ **重要提醒**：局域网 HTTP 模式下，**部分手机浏览器会因为安全策略拒绝开启麦克风**（尤其是 iOS Safari 和新版 Android Chrome）。如果遇到麦克风不工作的问题，请使用下面的 HTTPS 方案。

#### 场景 C：本地电脑 + 手机正式使用（HTTPS）

如果你想在手机上长期稳定使用语音通话功能，就需要配置 HTTPS。这里介绍最简单的方案：使用 **Caddy** 做反向代理。

> 🤔 **什么是反向代理？为什么需要它？**
> 手机浏览器出于安全考虑，只有在 HTTPS（加密连接）的网页中才允许使用麦克风。你的插件本身只提供 HTTP 服务，所以需要一个"中间人"（反向代理）来帮你处理加密。Caddy 就是这个中间人，它会自动帮你申请 HTTPS 证书。

**但是**，在本地电脑上配置 HTTPS 比较麻烦，因为你需要一个域名指向你的电脑。如果你没有域名和公网 IP，有两个选择：

1. **使用 Tailscale/ZeroTier 等内网穿透工具**搭配它们提供的域名。
2. **直接租一台便宜的云服务器**（见下方"情况二"），省心省力。

如果你有域名和公网 IP（或者做了端口映射），请参考下方"情况二"中的 Caddy 配置步骤，原理完全一样。

---

### 情况二：云服务器 (VPS) 部署

"云端部署"是指你的 AstrBot 运行在一台云服务器上（比如阿里云、腾讯云、AWS 等）。这种情况下配置 HTTPS 最简单，强烈推荐。

#### 你需要准备的东西

1. ✅ 一台运行着 AstrBot 的云服务器（已经有了）
2. ✅ 一个域名（便宜的域名一年大概不到 10 块钱，去阿里云或腾讯云买一个）
3. ✅ 域名已经完成备案（国内服务器需要；海外服务器不需要）

#### 第 1 步：域名解析

去你的域名服务商（阿里云/腾讯云/Cloudflare）的 DNS 管理页面，添加一条 A 记录：

| 记录类型 | 主机记录 | 记录值 | TTL |
|---------|---------|-------|-----|
| A | voice | 你的服务器公网 IP，比如 `123.45.67.89` | 600 |

这样 `voice.你的域名.com` 就指向了你的服务器。

> 💡 等几分钟让 DNS 生效。可以在电脑上 `ping voice.你的域名.com` 看看是否已经解析到你的服务器 IP。

#### 第 2 步：安装 Caddy

Caddy 是一个自动配置 HTTPS 的 Web 服务器，比 Nginx 简单很多。

**Ubuntu / Debian：**

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

**CentOS / RHEL：**

```bash
sudo yum install yum-plugin-copr
sudo yum copr enable @caddy/caddy
sudo yum install caddy
```

装好以后验证一下：

```bash
caddy version
```

能输出版本号就说明安装成功了。

#### 第 3 步：配置 Caddy

编辑 Caddy 的配置文件：

```bash
sudo nano /etc/caddy/Caddyfile
```

把里面的内容全部删掉，替换成下面的内容（**记得把下面【你的域名】改成你自己的**）：

```caddyfile
voice.你的域名.com {
    reverse_proxy 127.0.0.1:6888
}
```

就这三行就够了。Caddy 会自动干下面这些事情：
- 自动申请 Let's Encrypt 免费 HTTPS 证书
- 自动续期证书
- 自动把 HTTP 请求重定向到 HTTPS
- 自动转发 WebSocket 连接

保存文件后，重启 Caddy：

```bash
sudo systemctl restart caddy
sudo systemctl enable caddy   # 设置开机自启
```

查看 Caddy 是否正常运行：

```bash
sudo systemctl status caddy
```

如果显示 `active (running)` 就成功了。

#### 第 4 步：服务器防火墙放行端口

Caddy 需要用到 80 和 443 端口。**不需要**放行 6888 端口（6888 只在本机内部使用，不暴露到公网）。

**服务器系统防火墙：**

```bash
# Ubuntu (ufw)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# CentOS (firewalld) 
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

**云服务商安全组：**
还需要去你的云服务商控制台（阿里云/腾讯云），在安全组规则里放行 TCP 80 和 443。
具体操作：登录控制台 → 找到你的服务器 → 安全组 → 添加入站规则 → 允许 TCP 80 和 443。

> ⚠️ **千万不要在安全组里放行 6888 端口**，否则别人可以绕过 HTTPS 和 Caddy 直接访问你的插件，不安全。

#### 第 5 步：修改插件配置

在 AstrBot 管理面板中，把插件配置改为：

```
webui_host（网页监听 IP） = 127.0.0.1          ← 保持不变，不要改成 0.0.0.0
webui_port（网页监听端口） = 6888               ← 保持不变
webui_public_url = https://voice.你的域名.com/   ← 改成你的域名
webui_password = 这里填一个至少16位的强密码     ← 必须修改！
```

然后重启 AstrBot。

#### 第 6 步：手机访问

在手机浏览器中打开：

```
https://voice.你的域名.com/
```

输入你设置的密码，进入通话页面。点击"拨打电话"或"接听"时，浏览器会请求麦克风权限，点"允许"即可。

> 💡 因为是 HTTPS 页面，手机浏览器会正常弹出麦克风权限请求，语音通话功能完全正常。

---

### 🔧 Nginx 方案（可选）

如果你更熟悉 Nginx 或者服务器上已经装了 Nginx，也可以用 Nginx 做反向代理。但相比 Caddy，Nginx 需要你自己处理 HTTPS 证书（用 certbot）。

**安装 Nginx 和 Certbot：**

```bash
sudo apt install nginx certbot python3-certbot-nginx
```

**Nginx 配置文件** `/etc/nginx/sites-available/voicecall`：

```nginx
server {
    listen 80;
    server_name voice.你的域名.com;

    location / {
        proxy_pass http://127.0.0.1:6888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # WebSocket 支持（必须加！）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

启用配置并申请证书：

```bash
sudo ln -s /etc/nginx/sites-available/voicecall /etc/nginx/sites-enabled/
sudo nginx -t            # 检查配置有没有语法错误
sudo systemctl reload nginx
sudo certbot --nginx -d voice.你的域名.com   # 自动申请证书并修改 Nginx 配置
```

Certbot 会自动帮你把 Nginx 配置改成 HTTPS 的。之后访问方式和 Caddy 一样。

---

## ❓ 常见问题排查

### Q：手机打开页面后显示"无法使用麦克风"
**A：** 你在用 HTTP（而不是 HTTPS）访问网页。移动端浏览器只允许在 HTTPS 页面中使用麦克风。请参考上面的部署教程配置 HTTPS。

### Q：能打开网页但是点击拨号没反应
**A：** 检查右上角的绿色/红色小圆点。红色表示 WebSocket 没连上。可能原因：
- 插件没启动或报错了，检查 AstrBot 日志
- 端口被防火墙拦截了
- Nginx/Caddy 没有正确转发 WebSocket（检查 `proxy_set_header Upgrade` 配置）

### Q：AI 能接听但是听不到声音
**A：** 
- 检查手机没有开静音模式
- 检查手机媒体音量（不是铃声音量）是否调大了
- 检查网页右下角的扬声器按钮是否被点成了关闭状态
- iPhone 用户请确认使用 Safari 浏览器（Chrome for iOS 对音频支持有限制）

### Q：AI 听不懂我说的话 / 语音识别不准确
**A：**
- 确认你的 STT API Key 已正确填写
- 在安静的环境下测试
- 尝试更换 STT 模型（如使用 Groq 的 `whisper-large-v3-turbo`，识别速度更快）
- 在 `openai_stt_prompt` 中填写一些常用词帮助识别

### Q：AI 不接电话 / 回复格式不对
**A：** 检查你的人设提示词中是否正确添加了上面"人设提示词配置"部分的内容。AI 必须严格使用 `【接听通话】`、`【拒绝通话】` 等格式回复，插件才能识别。

### Q：`127.0.0.1` 和 `0.0.0.0` 有什么区别？
**A：**
- `127.0.0.1`：只有本机能访问，最安全。配合 Caddy/Nginx 反向代理时用这个。
- `0.0.0.0`：本机和局域网内所有设备都能直接访问。仅在局域网临时测试时使用。

---

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。

---

**Developed with ❤️ by [@nikonotnicotine](https://github.com/nikonotnicotine)**
```