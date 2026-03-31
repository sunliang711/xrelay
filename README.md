# xrelay

xrelay 是一个 [Xray-core](https://github.com/XTLS/Xray-core) 服务管理工具，通过 systemd 模板单元（`xray@<name>.service`）管理多个 xray 实例。

## 功能

- **多实例管理** — 基于 systemd 模板单元，一台机器可同时运行多个互不干扰的 xray 实例
- **YAML 配置** — 用简洁的 YAML 编写配置，自动渲染为 xray 所需的 JSON
- **一键安装** — 自动下载 xray 二进制、创建 venv、安装 systemd 服务
- **流量统计** — 通过 xray 内置的 gRPC Stats API 实时查看各 inbound/用户的上下行流量
- **定时记录** — 通过 cron 定期保存流量快照到本地文件，方便回溯
- **日志跟踪** — 快速查看 journalctl 服务日志

## 原理

```
┌─────────────────────────────────────────────────────────┐
│                      xray.py CLI                        │
│  add / start / stop / restart / config / log / traffic  │
└────────────────────────┬────────────────────────────────┘
                         │
            ┌────────────┼────────────────┐
            ▼            ▼                ▼
    ┌──────────┐  ┌────────────┐  ┌──────────────┐
    │ yaml2json│  │  systemctl │  │ xray stats   │
    │          │  │            │  │ API (gRPC)   │
    │ YAML     │  │ xray@name  │  │              │
    │  ↓       │  │  .service  │  │ statsquery   │
    │ Python   │  │            │  │  -s 127.0.0.1│
    │  ↓       │  │ start/stop │  │  :<api_port> │
    │ JSON     │  │ restart    │  │              │
    └──────────┘  └────────────┘  └──────────────┘
```

### 配置生成

1. 用户编写 `etc/<name>.yaml`，使用简洁的 YAML 语法描述 inbound（shadowsocks、vmess、socks5、http）和 outbound
2. `yaml2json.py` 读取 YAML，做字段校验后直接生成完整的 xray JSON 配置
3. 生成的 JSON 自动包含 `api`（StatsService）、`stats`、`policy` 等段落，开箱即用

### 服务管理

利用 systemd 模板单元 `xray@.service`，每个实例对应一个 `xray@<name>.service`：

- `ExecStartPre` — 检查 xray 二进制和配置文件是否就绪
- `ExecStart` — `xray run -c etc/<name>.json`
- `ExecStartPost` — 可选的启动后钩子（cron 等）
- `ExecStopPost` — 可选的停止后钩子

### 流量统计

通过 xray 内置的 gRPC Stats API 查询流量，无需 iptables：

- 每个 inbound 的 tag 格式为 `type:port:remark`（如 `ss:4000:nicof`）
- xray 统计项命名规则：`inbound>>>tag>>>traffic>>>uplink/downlink`
- vmess 支持按用户（email）统计：`user>>>email>>>traffic>>>uplink/downlink`
- `saveHour` 记录“距离上次保存”的增量，并同步更新小时 / 天 / 月三个粒度的统计文件

## 项目结构

```
xrelay/
├── install.py                 # 安装 / 卸载脚本
├── download.py                # 下载 xray release（GitHub / R2）
├── bin/
│   ├── xray.py                # CLI 入口（symlink 到 /usr/local/bin/xray.py）
│   └── xray_lib/
│       ├── config.py          # 路径常量
│       ├── service.py         # 服务管理（add/start/stop/restart/remove）
│       ├── traffic.py         # 流量统计（xray stats API）
│       ├── cron.py            # cron 定时任务管理
│       ├── log.py             # 彩色日志输出
│       └── utils.py           # 通用工具函数
├── template/
│   ├── config.yaml            # 新建实例时的 YAML 模板
│   └── xray@.service          # systemd 模板单元
├── yaml2json/
│   ├── yaml2json.py           # YAML → JSON 转换器
│   ├── tmpl                   # 旧模板文件（兼容保留）
│   └── requirments.txt        # Python 依赖（pyyaml）
├── etc/                       # [运行时生成] 实例配置文件（.yaml + .json）
└── apps/
    └── net-traffic/           # [运行时生成] 流量统计日志
```

## 系统要求

- Linux（需要 systemd）
- Python 3.10+
- python3-venv（Debian/Ubuntu: `apt install python3.x-venv`）
- sudo 权限

## 安装

```
git clone <repo-url> xrelay
cd xrelay
sudo python3 install.py install
```

安装过程会自动完成以下步骤：

1. 检查 python3-venv 是否可用
2. 下载最新版 xray release → 安装到 `/usr/local/bin/xray`
3. 创建 yaml2json 虚拟环境并安装 Python 依赖（pyyaml）
4. 创建 `clash` 系统组
5. 创建符号链接 `bin/xray.py` → `/usr/local/bin/xray.py`
6. 生成并安装 systemd 模板单元 `xray@.service`

安装完成后即可使用 `xray.py` 命令。

## 卸载

```
sudo python3 install.py uninstall
```

## 使用

### 实例管理

```bash
# 创建新实例（打开编辑器编写 YAML 配置）
xray.py add myserver

# 列出所有实例
xray.py list

# 编辑配置（保存后自动重启）
xray.py config myserver

# 启动 / 停止 / 重启
xray.py start   myserver
xray.py stop    myserver
xray.py restart myserver

# 查看日志（journalctl -f）
xray.py log myserver

# 删除实例
xray.py remove    myserver
xray.py removeAll
```

### 流量统计

```bash
# 实时监控（每秒刷新，Ctrl+C 退出）
xray.py traffic monitor myserver

# 单次快照
xray.py traffic show myserver

# 保存每小时快照到月度文件
xray.py traffic saveHour myserver

# 手动补记一次“距离上次保存”的增量，并刷新当天 / 当月汇总
xray.py traffic saveDay myserver

# 查看历史记录
xray.py traffic day   myserver   # 当天汇总文件
xray.py traffic hour  myserver   # 当月小时日志
xray.py traffic month myserver   # 当月汇总文件
```

流量统计输出示例：

```
2025-01-15T14:30:00

=== Inbound Traffic ===
type      port      remark              uplink              downlink            total
----------------------------------------------------------------------------------------------------
ss        4000      nicof               1,234,567           9,876,543           11,111,110
socks5    4020      noauth              456,789             3,210,987           3,667,776
http      4030      noauth              12,345              67,890              80,235
----------------------------------------------------------------------------------------------------

=== User (vmess) Traffic ===
email                         uplink              downlink            total
------------------------------------------------------------------------------------------
vmess:4010:nicof              2,345,678           8,765,432           11,111,110
------------------------------------------------------------------------------------------
```

### 配合 cron 自动记录

在 systemd 钩子中启用 cron（编辑 `service.py` 中的 `cmd_start_post` / `cmd_stop_post`，取消注释 `add_cron` / `del_cron`），服务启动时自动注册定时任务：

- 每小时整点：`xray.py traffic saveHour <name>`
- 如需在手动补采样时刷新当天 / 当月汇总：`xray.py traffic saveDay <name>`

### 配置文件格式

YAML 配置文件位于 `etc/<name>.yaml`，结构如下：

```yaml
inbounds:
  config:
    loglevel: info
    logfile: ""
    log_access: ""
    log_error: ""
    vmess_port: 4110          # vmess 共用端口
    vmess_network: raw        # vmess 传输方式
    api_port: 18080           # Stats API 端口

  shadowsocks:
    - user: alice
      tag: "ss:4000:alice"
      server: 1.2.3.4
      cipher: aes-256-gcm
      password: your-password
      udp: true
      sub: true

  vmess:
    - user: bob
      tag: "vmess:4010:bob"
      server: 1.2.3.4
      cipher: auto
      uuid: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
      alterId: 0
      sub: true

  socks5:
    - user: charlie
      tag: "socks5:4020:noauth"
      server: 1.2.3.4
      udp: true
      auth: noauth
      sub: true

  http:
    - user: dave
      tag: "http:4030:noauth"
      server: 1.2.3.4
      sub: true

  outbound:
    protocol: socks
    server: localhost
    port: 7891
```

**tag 格式**：`protocol:port:remark`，例如 `ss:4000:alice`。tag 同时用于 xray 的 inbound 标识和流量统计的索引键。

## 日志级别

```bash
xray.py -l debug start myserver
```

可选级别：`fatal` / `error` / `warning` / `info`（默认）/ `success` / `debug`

## License

MIT
