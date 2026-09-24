# VPS-SQLite-API

东方财富公告原始数据采集、SQLite 存储、管理面板和 API 服务。

## 一键安装

在 Debian/Ubuntu 类 VPS 上以 root 或 sudo 运行：

```bash
curl -fsSL https://raw.githubusercontent.com/baibiaowang/VPS-SQLite-API/main/install.sh | sudo bash
```

首次安装会要求设置管理面板密码，并生成一次性 API Token。

## 服务

- 管理面板：`/admin/login`
- API 文档：`/docs`
- API：`/api/v1/*`
- 数据库：`/opt/eastmoney/data/eastmoney.db`
- 原始 Eastmoney JSON：`/opt/eastmoney/data/raw/`
- 数据库备份：`/opt/eastmoney/data/backup/`

采集调度统一由 `eastmoney-scheduler.timer` 负责。旧版固定 23:30 的 `eastmoney-fetch.timer` 不再由安装脚本启用，避免与面板配置产生双重采集。

## 防重复与防过载

采集器使用系统级文件锁，手动、定时和其他采集任务不能同时执行。

请求次数写入 SQLite 的 `request_stats` 表，跨进程和重启持久化；面板可以调整每日上限、并发、最小请求间隔、随机抖动、重试和退避。

收到 HTTP 403/429 后进入冷却期，避免继续连续请求。采集页不足以覆盖 Eastmoney 返回的 `total_hits` 时，本次事务回滚，不把不完整数据记录成成功。

## HTTPS

生产环境建议让 Caddy/Nginx 对外提供 HTTPS，再反向代理到 127.0.0.1:8080。不要把 SQLite、raw 数据目录或 /etc/eastmoney/eastmoney.env 暴露给公网。

`deploy/Caddyfile.example` 提供了 Caddy 示例配置。

## 数据原则

原始 Eastmoney 返回值保存在 `announcements.raw_json` 和 raw JSON 文件中；分析字段独立存储在 `analysis_results`，采集层不会覆盖分析结果。

数据库通过 `art_code` 去重，并单独保存公告与股票、Eastmoney 栏目的关系。

## 运维

查看 API：

```bash
systemctl status eastmoney-api
journalctl -u eastmoney-api -f
```

查看调度：

```bash
systemctl status eastmoney-scheduler.timer
journalctl -u eastmoney-scheduler.service -f
```

手动增量采集：

```bash
systemctl start eastmoney-fetch.service
```

立即备份：

```bash
systemctl start eastmoney-backup.service
```

采集锁文件位于 `/opt/eastmoney/data/collector.lock`，服务异常退出后系统锁会释放；下一次调度可继续接管。

## 开发检查

GitHub Actions 会运行 Python 编译检查、依赖安装、单元测试以及 Bash 语法检查。

