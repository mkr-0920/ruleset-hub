# ruleset-hub

以 [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) 的 `meta` 分支为唯一规则源，按个人策略合并，生成 Mihomo MRS 二进制规则。每天北京时间 **08:00** 自动构建并更新 GitHub **Release 附件**，固定标签为 `latest`。

[最新 Release](https://github.com/mkr-0920/ruleset-hub/releases/tag/latest) · [完整订阅配置片段](https://github.com/mkr-0920/ruleset-hub/releases/download/latest/mihomo.yaml) · [构建状态](https://github.com/mkr-0920/ruleset-hub/actions/workflows/build.yml)

## 启用自动发布

1. 将本项目推送到你自己的 GitHub 仓库，默认分支使用 `main` 或 `master`。
2. 在 **Actions → Build and release MRS → Run workflow** 运行首次构建。后续规则配置、脚本变更会自动触发，每天也会定时构建。
3. 构建成功后，在 **Releases → Latest MRS rules** 获取文件。复制附件 `rule-providers.yaml` 和 `rules.yaml` 的内容到现有 Mihomo 配置的对应位置。

工作流使用仓库自带的 `GITHUB_TOKEN`，发布 job 已声明 `contents: write`，通常不需要个人 Token。仓库/组织策略必须允许 Actions 创建 Release。定时任务只在默认分支运行；GitHub 可能延迟调度，长期无活动的公共仓库也可能被暂停定时任务，需要在 Actions 页面重新启用。

自动生成的配置会使用实际的 `owner/repo`，不需要手工修改构建脚本。GitHub Release 附件供客户端直接下载时，仓库应为公开仓库。

## 在 Mihomo 中订阅

当前仓库可直接使用以下地址。Fork 到其他仓库时，替换 URL 中的 `mkr-0920/ruleset-hub`：

```yaml
rule-providers:
  private:
    type: http
    behavior: domain
    format: mrs
    path: ./ruleset/private.mrs
    url: "https://github.com/mkr-0920/ruleset-hub/releases/download/latest/private.mrs"
    interval: 86400
    proxy: PROXY

rules:
  - RULE-SET,private,DIRECT
  # 使用发布的 rules.yaml 获取完整顺序，最后一条是 MATCH,漏网之鱼。
```

下载 URL、文件名和 `latest` 标签始终保持固定。构建每天执行一次，客户端独立地按 `interval: 86400` 每 24 小时检查一次。首次下载需要配置中已有可用的 `PROXY` 策略组及代理节点。

发布的配置片段不包含代理节点、代理组或 DNS。需要在现有配置中保留 `HOME`、`AI`、`TELEGRAM`、`GOOGLE`、`NETFLIX`、`PROXY`、`漏网之鱼` 策略组。`DIRECT`、`REJECT` 为内置策略。

## 产物与优先级

个人强制规则最先匹配，然后按下表顺序匹配。相同策略但优先级不同的域名规则不会合并。

| 文件 | behavior | 策略 | 上游集合 |
|---|---|---|---|
| `ads.mrs` | domain | REJECT | category-ads-all |
| `private.mrs` | domain | DIRECT | private |
| `ai-cn.mrs` | domain | DIRECT | category-ai-cn |
| `ai.mrs` | domain | AI | category-ai-!cn |
| `telegram.mrs` | domain | TELEGRAM | telegram |
| `telegramip.mrs` | ipcidr | TELEGRAM，no-resolve | telegram |
| `google.mrs` | domain | GOOGLE | google、google-cn、youtube |
| `netflix.mrs` | domain | NETFLIX | netflix |
| `direct-services.mrs` | domain | DIRECT | microsoft@cn、apple-cn、bilibili、category-games-cn、category-games@cn |
| `tracker.mrs` | domain | DIRECT | tracker |
| `onedrive.mrs` | domain | PROXY | onedrive |
| `netflixip.mrs` | ipcidr | NETFLIX | netflix |
| `proxy.mrs` | domain | PROXY | apple-tvplus、disney、hbo、primevideo、tiktok、spotify、category-games-!cn、gfw、geolocation-!cn、tld-!cn |
| `cn.mrs` | domain | DIRECT | cn |
| `directip.mrs` | ipcidr | DIRECT，no-resolve | private、cn |

域名来源路径为 `geo/geosite/<集合>.list`，IP 来源为 `geo/geoip/<集合>.list`。第一版不包含 `applications`、`networktest`、`mediaip`；通用 `media` 别名不另建产物，使用明确的流媒体集合与代理大盘覆盖。

每次发布还包含对应的 `.list` 文本、`rule-providers.yaml`、`rules.yaml`、合并后的 `mihomo.yaml` 配置片段、`manifest.json` 和 `SHA256SUMS`。`mihomo.yaml` 同样是片段，不是包含节点和策略组的完整配置。

## 修改个人规则

- `config/custom-rules.yaml`：维护最高优先级的个人规则，保留原顺序。`navidrome.010920.xyz → HOME` 在 `010920.xyz → DIRECT` 之前。
- `config/bundles.yaml`：每个产物的来源、策略与顺序。调整集合只需修改这里；移除 `proxy.sources` 中的 `tld-!cn` 可关闭外国顶级域名的宽泛匹配。

国内 AI 明确直连，位于国外 AI 之前；国外 AI 位于 Google 之前，避免 Gemini 被 Google 大集合覆盖。国内服务例外位于代理大盘之前，`cn` 国内大盘位于代理大盘之后。Netflix IP 沿用原配置，不添加 `no-resolve`。

`tracker.mrs` 只控制 BT/PT Tracker 域名请求，Peer 下载连接仍按其他规则处理。`onedrive.mrs` 独立维护，默认沿用 PROXY；需要直连时，将 `config/bundles.yaml` 中 `onedrive.policy` 改成 `DIRECT`，下一次构建会同步生成分流配置。个人强制规则仍有最高优先级。

## 微软服务的分流建议

使用 `microsoft@cn` 标记的国内服务及下载/CDN 规则直连，已包含在 `direct-services.mrs`；不要将整个 `microsoft` 集合全部直连。Copilot 由更靠前的 `ai.mrs` 交给 AI 策略组，OneDrive 默认走独立的 PROXY 规则，其他微软流量按后续大盘规则处理。

`direct-services` 位于 `onedrive` 之前，确保两者重叠的 `sharepoint.cn` 仍然直连。直连效果取决于本地网络；如果需要调整 OneDrive，独立修改该集合即可。

只合并上游文本规则，不拼接二进制 MRS。不将精确域名扩展为后缀匹配，不对域名进行跨策略删除。IP 合并使用无损 CIDR 折叠，分别处理 IPv4/IPv6。

## 本地构建

需要 Python 3.12+。Windows/Linux x64 会自动下载固定版本 Mihomo，并检查下载包的 SHA256：

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/build.py --repository mkr-0920/ruleset-hub
```

产物写入 `dist/`。其他平台或使用已有内核时：

```text
python scripts/build.py --repository owner/repo --mihomo /path/to/mihomo
```

可添加 `--upstream-ref <40位提交SHA>` 复现指定上游快照。编译器版本固定在 `scripts/install_mihomo.py`；更新版本时须同步更新两种平台下载包的 SHA256。

## 构建与发布保障

每次先解析上游提交 SHA，所有源文件都从同一提交下载。缺失、空白或非法来源直接使构建失败；先在临时目录完成 15 个 MRS 的转换、反解覆盖范围校验和 Mihomo 配置检查，成功后才替换本地 `dist/`。上游数据与最终文件的 SHA256、来源提交、条目数均记录在清单中。`count` 是合并文本条目数，`compiled_count` 是反解条目数；内核可能省略已被后缀覆盖的精确规则，两者可以不同。

Release job 只在默认分支、且构建校验全部通过后运行；PR 仅验证，不发布。发布前再次核对产物 SHA256。使用同名附件覆盖，保持订阅地址稳定；构建失败不会上传，也不会删除既有 Release。附件逐个更新，`manifest.json` 最后上传，用于核对本批次版本。

规则内容及其许可证归上游及原作者所有，本项目保留来源链接和每批次来源记录。
