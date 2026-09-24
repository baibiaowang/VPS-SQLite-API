# 安全部署建议

1. 管理面板必须使用 HTTPS。
2. API Token 不提交 GitHub；安装器只保存 SHA-256 哈希。
3. 管理密码使用 PBKDF2-SHA256 哈希。
4. /etc/eastmoney/eastmoney.env 权限为 600。
5. SQLite 与 raw JSON 不在仓库。
6. systemd 使用 eastmoney 专用低权限账户。
7. 生产环境只开放 SSH、80、443；不要暴露 8000、数据库文件或 /opt/eastmoney/data。
8. 如果使用 Caddy，DNS 指向 VPS 后，把 deploy/Caddyfile.example 内容复制到 Caddy 配置并 reload。
9. API 请求必须带 Authorization: Bearer Token。
10. 管理操作使用签名 Session + CSRF。
