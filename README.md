# HidenCloud 自动续期

# 没精力更新了，[到老王项目继续使用。](https://github.com/eooce/Auto-Renew-HidenCloud) 

> ⭐ 觉得有用？给个 Star 支持一下！  
> 官网：[https://hidencloud.com](https://hidencloud.com) ｜ 控制台：[https://dash.hidencloud.com](https://dash.hidencloud.com) ｜ 实时库存监控频道 [oyz8_bot](https://t.me/oyz8_bot)

自动续期 [HidenCloud](https://hidencloud.com) 免费 VPS 服务器，防止到期被删除。

通过 GitHub Actions 定时运行，使用 SeleniumBase 模拟浏览器操作完成续期，支持 Telegram 通知、多协议代理连接、自动调整下次执行时间。

## 功能

- 自动登录并续期 HidenCloud 免费服务器  
- 自动检测到期时间，提前约 20 小时执行续期  
- 自动处理 Cloudflare Turnstile 验证  
- 智能识别续期限制（如未到可续天数）并通知  
- Telegram 机器人推送续期结果（含截图）  
- 支持多种代理协议（VLESS / VMess / Trojan / Shadowsocks / SOCKS5）  
- 浏览器状态缓存，避免每次重复登录  
- 续期成功后自动更新工作流 Cron 表达式，精准控制下次运行时间  
- 自动清理历史工作流运行记录，仅保留最近 2 次  

## 配置

在仓库 `Settings → Secrets and variables → Actions` 中添加以下 Secrets：

| Secret 名称 | 必填 | 说明 | 示例 |
|---|---|---|---|
| `HIDENCLOUD` | ✅ | HidenCloud 账号信息 | 见下方格式 |
| `REPO_TOKEN` | ✅ | 用于推送 Cron 更新的 GitHub Token | `ghp_xxxxxxxxxxxxxxxxxxxx`（需要特定权限，见下文） |
| `PROXY_NODE` | ✅ | 代理节点地址，支持多种协议 | 见下方代理格式 |
| `TG_BOT_TOKEN` | ❌ | Telegram Bot Token | `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
| `TG_CHAT_ID` | ❌ | Telegram Chat ID | `123456789` |



### ⚙️ REPO_TOKEN 权限要求

- `REPO_TOKEN` 必须是 **Personal Access Token (Classic)**，且创建时务必勾选 **`repo`** 和 **`workflow`** 两项权限，否则将无法自动更新工作流中的 Cron 定时规则。
- 获取路径：GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)  
  如不需要自动调整 Cron，可在编辑工作流文件后移除相关步骤，此时可省略该 Secret。

### HIDENCLOUD 格式

邮箱和密码用 `-----` 分隔（目前仅支持单账号）：

```
myaccount@mail.com-----MyStr0ngP@ssw0rd
```

### 代理格式（最好本地浏览器试试能不能登陆再用）`最好用注册号的代理`

`PROXY_NODE` 支持以下任意一种代理协议的完整分享链接（不配置则直连）：

- **VLESS**：`vless://uuid@server:port?security=reality&sni=...&type=ws&...`
- **VMess**：`vmess://base64encoded`
- **Trojan**：`trojan://password@server:port?sni=...&type=ws&...`
- **Shadowsocks**：`ss://base64@server:port`
- **SOCKS5**：`socks5://user:pass@server:port` 或 `socks5://server:port`

## 使用

### GitHub Actions（推荐）

1. Fork 本仓库  
2. 在仓库 Secrets 中配置 `HIDENCLOUD` 和 `REPO_TOKEN`（注意 PAT 权限）  
3. （可选）配置 `TG_BOT_TOKEN`、`TG_CHAT_ID`、`PROXY_NODE`  
4. 工作流会按初始 Cron 计划运行，首次成功后会自动计算并更新为最优的后续执行时间  
5. 你也可以随时在 Actions 页面手动触发 `workflow_dispatch`  

## 注意事项

- Cloudflare Turnstile 验证有一定失败概率，脚本已内置等待与重试机制  
- 工作流会自动修改 `.github/workflows/HidenCloud_Renew.yml` 中的 Cron 表达式，请确保 Actions 有写入权限  
- 浏览器状态缓存在 GitHub Actions Cache 中，可加速后续运行，每次执行后会自动清理旧缓存  
- 日志和 Telegram 通知中的敏感信息（邮箱、服务器 ID 等）均已脱敏处理  
- 代理为可选项，若在国内环境运行，建议配置代理以提高稳定性  

---

**⚠️ 免责声明**：本脚本仅供学习交流使用，使用者需遵守 [HidenCloud](https://hidencloud.com) 的服务条款。因使用本脚本造成的任何问题，作者不承担任何责任。
