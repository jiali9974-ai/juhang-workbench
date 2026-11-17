# 云端自动同步

源码以 `jiali9974-ai/juhang-workbench` 的 `main` 为准。提交并推送后，GitHub 的
`push` webhook 立即触发拉取；systemd timer 每 30 秒补查一次，漏掉通知或临时断网后也会继续同步。
前端需要构建，通常在推送后几十秒完成；有识别、剪辑或生成任务时，等任务结束后再切换。
本地未提交、未推送的改动不会部署。

- `/srv/jh-workbench/source.git`：使用仓库专用只读 SSH deploy key 拉取。
- `/srv/jh-workbench/releases/`：每个版本独立的 Git worktree，`app` 是当前版本的符号链接。
- 前端从该提交的源码和 lockfile 构建；配置生成、Python 导入和接口检查全部通过后才记录部署成功。
- 切换后健康检查失败会恢复旧代码和旧配置。原来的手动上传目录保留在 `backups/`。
- 素材、成片、模型、API 密钥保存在版本目录外，`config.server.yaml` 单独生成 Linux 路径和 CPU 设置。
- `automation/` 保存本机安装的部署器和 webhook 接收器；修改这些基础设施文件后需单独安装并验证，
  应用的 Git 更新不会自行覆盖正在运行的部署器。
- webhook secret、SSH 私钥、API 密钥均不进入 Git。webhook 仅接受正确签名的本仓库 `main` 推送。
- 当前沿用已有 HTTP 8765 端口接收通知；没有 TLS。通知只用于唤醒拉取，源码通过 SSH 读取。
- 本地代码不会被云端反向覆盖；每次同步也会检查当前版本是否存在源码漂移。
- releases 和依赖缓存保留以便回退，需要按磁盘使用情况定期清理。

查看运行状态（服务器上执行）：

```bash
cat /srv/jh-workbench/deployed-revision
git -C /srv/jh-workbench/app status --short --branch
systemctl status jh-workbench-sync.timer jh-workbench-webhook --no-pager
journalctl -u jh-workbench-sync.service -n 60 --no-pager
```

手动触发一次：`sudo systemctl start jh-workbench-sync.service`，或在本地 Git Bash 运行
`bash deploy/deploy.sh`。手动部署也只拉取 GitHub 的 `main`，不再上传本地压缩包。

恢复一个历史版本：暂停 `jh-workbench-sync.timer` 和 `jh-workbench-webhook.service`，
把 `app` 链接切换至对应 release，恢复该次备份的配置，再重启 `jh-workbench`。
排查完问题后，应在 GitHub `main` 修复或回退提交，再开启自动同步，避免被覆盖。
