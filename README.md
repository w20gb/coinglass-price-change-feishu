# Coinglass 价格异动监控 (GitHub Actions版)

## 📌 项目简介
利用 GitHub Actions 的云端能力，每隔 **5-10分钟** 自动启动无头浏览器 (Playwright)，
访问 Coinglass 获取全市场 USDT 合约最新价格，并与上一次运行的数据进行对比。
当发现涨跌幅超过阈值（如 ±2%）时，自动推送飞书消息。

## 🌟 核心功能
1.  **云端运行**：无需本地挂机，由 GitHub 免费服务器代劳。
2.  **趋势捕捉**：通过对比 "本次 vs 上次" 的价格，捕捉 5-10 分钟级别的趋势异动。
3.  **飞书推送**：异动信息直达飞书群。
4.  **历史回写**：自动将最新价格写入 `history_data.json` 并提交回仓库，形成闭环。

## 🚀 部署步骤
1.  **Fork/Upload**：将本项目上传至您的 GitHub 私有仓库。
2.  **配置 Secrets**：
    *   在仓库 `Settings` -> `Secrets and variables` -> `Actions` 中添加：
    *   `FEISHU_WEBHOOK`: 您的飞书机器人 Webhook 地址。
    *   `ACCESS_TOKEN`: (可选) 如果默认 GITHUB_TOKEN 权限不足，需申请 PAT。
3.  **启动**：
    *   Actions 会根据 `.github/workflows/monitor.yml` 自动运行。
    *   您也可以在 `Actions` 页面手动点击 `Run workflow` 测试。

## ⚠️ 注意事项
*   **频率限制**：GitHub Actions 的定时任务由官方调度，`cron: "*/5 * * * *"` 并不保证精确的 5 分钟间隔，可能会有延迟。
*   **提交记录**：由于脚本会自动 commit 历史数据，您的仓库 commit 记录会很多，请知悉。
