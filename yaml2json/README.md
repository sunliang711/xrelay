# yaml2json

`yaml2json.py` 用来把简化的 YAML 输入文件转换成 xray 可直接加载的 JSON 配置。

它主要服务于 `xrelay`，但也可以单独使用。

**脚本入口**
- 转换脚本：[yaml2json.py](/Users/eagle/Sync/clashsub/xrelay/yaml2json/yaml2json.py)
- 输入样例：[input-example.yaml](/Users/eagle/Sync/clashsub/xrelay/yaml2json/input-example.yaml)
- 当前仓库示例配置：[config.yaml](/Users/eagle/Sync/clashsub/xrelay/yaml2json/config.yaml)

**支持范围**
当前脚本支持的 inbound：

- `shadowsocks`
- `vmess`
- `socks5`
- `http`

当前脚本支持的 outbound：

- `socks`
- `http`
- `vless`
- `file`

说明：

- `vlessReality`、`hysteria`、`vmessWebsocket` 这些是 `clashsub` 主服务支持的字段，不属于当前 `yaml2json.py` 的处理范围
- 如果在这里写了不支持的 inbound，脚本不会把它们转换进输出 JSON

**输入规则**
1. 根节点必须是 `inbounds`
2. `inbounds.config` 和 `inbounds.outbound` 都必须存在
3. 所有 inbound 的 `tag` 必须符合 `type:port:remark` 格式
4. inbound 的实际端口只从 `tag` 解析

端口规则非常重要：

- `yaml2json.py` 在解析 inbound 时，会直接从 `tag` 取出端口并写回内部数据
- 即使 YAML 里额外写了独立的 `port` 字段，最终也会被 `tag` 中的端口覆盖
- 因此建议：inbound 不要写独立 `port` 字段，只维护 `tag`

兼容字段说明：

- `user`
- `server`
- `sub`

这些字段保留在样例里，主要是为了和 `clashsub` 其它输入文件风格保持一致；当前 `yaml2json.py` 生成 inbound JSON 时并不会使用它们。

**vmess 约束**
- 每条 `vmess` 都必须填写 `uuid`
- 每条 `vmess` 都必须填写 `network`
- 同一个文件中的所有 `vmess`，`tag` 中端口必须完全一致
- 同一个文件中的所有 `vmess`，`network` 必须完全一致

脚本会把多个 `vmess` 条目合并成一个 xray `vmess` inbound，并把每个条目写成一个 client。

**日志配置**
`inbounds.config` 中支持这些字段：

- `loglevel`
- `logfile`
- `log_access`
- `log_error`
- `api_port`

其中：

- 如果 `log_access` 为空，会回退使用 `logfile`
- 如果 `log_error` 为空，也会回退使用 `logfile`
- `api_port` 默认值是 `18080`

**使用方法**
在 `xrelay/yaml2json` 目录下执行：

```bash
python3 yaml2json.py --config input-example.yaml --output output.json
```

也可以显式传日志参数：

```bash
python3 yaml2json.py \
  --config input-example.yaml \
  --output output.json \
  --log-level info \
  --log-file /tmp/yaml2json.log
```

参数说明：

- `--config`：输入 YAML 文件，默认 `config.yaml`
- `--output`：输出 JSON 文件，默认 `config.json`
- `--template`：兼容历史参数，当前已不再使用
- `--log-level`：脚本日志级别
- `--log-file`：脚本日志输出文件

**outbound 说明**
`inbounds.outbound.protocol` 支持四种模式：

- `socks`
- `http`
- `vless`
- `file`

其中：

- `socks` / `http` 需要 `server` 和 `port`
- 若鉴权方式是 `password`，还需要 `username` 和 `password`
- `vless` 需要 `server`、`port`、`uuid`，其余字段有默认值
- `file` 会读取外部 JSON 文件；如果传相对路径，则相对于当前 YAML 文件所在目录解析

**快速上手**
1. 复制 [input-example.yaml](/Users/eagle/Sync/clashsub/xrelay/yaml2json/input-example.yaml) 为你的实例配置。
2. 按实际环境修改 `tag`、`uuid`、密码和 outbound。
3. 运行转换命令生成 JSON。
4. 用生成的 JSON 交给 xray 或 `xrelay` 实例去启动。
