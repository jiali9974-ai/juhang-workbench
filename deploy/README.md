# 云端自动同步

## AutoDL 素材剪辑服务器

新实例使用 `deploy/autodl/`，源码仓库仍为 `jiali9974-ai/juhang-workbench` 的 `main`。
每 30 秒通过仓库专用只读 deploy key 拉取一次；本地代码必须提交并推送后才会更新。
服务器地址由 AutoDL 控制台提供，SSH 密码不进入代码或 Git。

- 数据盘根目录：`/root/autodl-tmp/jh-workbench`，下文简称 `$BASE`。
- `materials/`、`outputs/`、`data/`、`models/`、`secrets.yaml` 独立于源码版本。
- `source.git/` 和 `releases/<提交>/` 保存 Git 源码；`current` 指向当前运行版本。
- Python 环境按 `deploy/autodl/requirements.txt` 内容分别缓存；前端依赖按 lockfile 缓存。
- 先安装依赖、构建前端、生成 Linux 配置和检查后端导入，再等待剪辑队列空闲后切换。
- 新版首页和接口检查失败时，恢复上一版源码、配置和 Python 环境。
- GPU 用于 SenseVoice 识别；每次部署实际测试 NVENC 编码会话，可用时自动启用。
  此实例的 vGPU 实测不开放 NVENC，因此视频导出自动使用 CPU 的 libx264；换整卡后无需手改配置。
  默认保留素材原声，不安装图生视频模型。
- 服务监听 `6006`，通过控制台「自定义服务」访问。
- 后台进程由独立 Supervisor 管理，`/etc/autodl.sh` 调用 `automation/start.sh` 开机启动。
- `automation/` 是已安装的部署基础设施；更新部署器本身后需单独安装，应用自动更新不自行替换部署器。

```bash
BASE=/root/autodl-tmp/jh-workbench
cat "$BASE/deployed-revision"
/root/miniconda3/bin/python -m supervisor.supervisorctl -c "$BASE/automation/supervisord.conf" status
tail -n 60 "$BASE/logs/sync.log" "$BASE/logs/sync-error.log"
# 手动检查更新；后台已在执行时会自动跳过
/root/miniconda3/bin/python "$BASE/automation/sync.py"
```

回退：先停 `jh-git-sync`，将 `current` 指向 `runtime/` 中上一版目录，再重启 `jh-workbench`。
修复或回退 GitHub `main` 后，再启动 `jh-git-sync`。

## 旧 CPU 服务器

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
- webhook 从已开放的 HTTP 80 端口 `/__jh_git_push` 接收通知，没有 TLS；仅该路径转给签名验证器。
  安装时在现有 80 端口 server 中加入 `nginx-jh-webhook-location.conf`，其余路径保持原站点处理。
  8765 端口也保留同一个签名入口。通知只用于唤醒拉取，源码通过 SSH 读取。
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
