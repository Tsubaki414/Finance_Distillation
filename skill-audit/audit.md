# 技能审计与配置结果

本轮安装了 9 个 skill；安装数量不计作产品完成度。逐文件 SHA、仓库提交、网络与凭证检查见 `skills.lock.json` 和 `repository-inventory.json`。运行和产物对应关系见 `skill-product-run-matrix.json`。

| 能力 | 审计决定 | 实际执行边界 |
|---|---|---|
| 官方 jupyter-notebook | 已安装、已使用 | 真实清洗语料的 notebook 已执行；输出保留，非示例数字。 |
| 官方 playwright | 已安装；连接预检未通过 | 当前 Chrome 没有可用的已授权 Playwright/CDP 会话。没有另开浏览器、重启 Chrome 或读取 cookie。现有窗口仅做了部分原生 UI 检查。 |
| 官方 screenshot | 已安装；系统权限预检被自动审核拒绝 | 没有取得终端持久录屏权限。官方财务表图片采用下载的公司原始 PDF 页面渲染，来源与哈希另记；不冒充操作系统截屏。 |
| Xquik-dev/x-twitter-scraper | **唯一选中的 X 新采集方案**；已安装，未启用 | 当前无 XQUIK_API_KEY，价格与接口契约仍需账户预检。新采集请求为 0。既有 Apify / RapidAPI 文件只是历史输入，不构成第二套正在运行的采集器。 |
| kohoj/skills/twitter-scraper | 拒绝，未安装、未运行 | 审计发现 CDP 读取 auth_token/ct0；带无域限制 cookie 和 CSRF 的客户端还会请求发现的脚本地址。仅用虚构值和 MockTransport 离线重现该凭证作用域问题。 |
| train-sentence-transformers | 已评估，暂缓 | 冻结 embedding 已有基线，尚无独立双语标签及训练获益证据。未启动微调。 |
| huggingface-community-evals | 已评估，暂缓 | 通用榜单不能替代金融忠实度与人设盲测。本项目先保留独立切分和本地结果，不上传用户语料。 |
| huggingface-trackio | 项目内安装并使用 | 本地记录 A/B/C 实验；未配置 Space 或 Hub 上传。 |
| yfinance-data / earnings-recap / estimate-analysis | 项目内安装并使用 | NVDA 实际 SDK 数据与公司 IR、10-Q、电话会原文对照。Yahoo 共识与实际值必须匹配 GAAP / non-GAAP 和财政期间。 |
| SEC EDGAR MCP | 第三方实现与传递依赖已审计、项目 venv 已安装；未启用 | 等待真实 SEC 联系身份。入口在缺失身份时于联网前退出；HTTPS 域名白名单、超时、全局每秒至多一次请求、脱敏日志。尚未实测 SEC 网络请求。 |
| financial-persona-distillation | 已创建、校验并用于本项目 | 实测语言特征、时间留出、同题跨时间相似度、引用重合与 AI-pattern 诊断、分角色权重、推广清理、原文证据位置。模型诊断不充当真人评审。 |

Xquik 执行前仍须验证当前接口契约，读取 credits，并用与正式任务完全一致的查询及条数调用估价接口，保存 `allowed / creditsRequired / creditsAvailable` 和预算上限。当前额度和价格未知，因此没有运行，也没有声称成本已通过。其凭证仅应作为 `x-api-key` 发往 `xquik.com`。授权的 RapidAPI key 不能替代它。

kohoj 审计定位：`twitter-scraper/scripts/cdp_tweet_fetcher.py:507–612`。`credential-scope-test.json` 是零网络、零真实凭证的离线测试，不代表发现了历史泄露。

金融 skill 的四项修正已进入运行：不能把财报日前后五天端点当成公告反应；日期必须排序；GAAP 与 non-GAAP 分开；不采用未经验证的“0.7 即看多”规则，也不对零或负分母给出误导性增长率。公司托管的原始 10-Q 与 SEC 独立抓取是两种来源状态，报告中分别标记。

writer-persona 与 Bespoke 仅提供方法参考，没有复制其固定阈值、身份或最终人设。当前三个人设的权重是可编辑的假设。观察到的作者识别能力不等于生成稿的人设可识别性；后者必须另做盲评。

官方 skill 安装后需要重新加载 Codex 才能在新会话的技能目录中出现。本轮已直接读取安装后的文件并使用所需脚本，没有重启用户应用。

来源：

- [OpenAI 官方 skills](https://github.com/openai/skills)
- [Xquik 候选代码](https://github.com/Xquik-dev/x-twitter-scraper/tree/98260596503409589f727b839e5bd3e2cff910e1)
- [kohoj 候选代码](https://github.com/kohoj/skills/tree/f9ee80710e228d4739f053423a73621b20cc5d09)
- [Hugging Face skills](https://github.com/huggingface/skills/tree/97862b0fcc89c850fdd00c82ede1e62d3c930a6d)
- [finance-skills](https://github.com/himself65/finance-skills/tree/0a5759bca1ea273790cd45c17fad6a9aff76a7f5)
- [writer-persona](https://github.com/cosmos-makers/writer-persona/tree/5eee0fd5b0c2ce00fc3bd12ea546efb163d96cf8)
- [Bespoke](https://github.com/blisse-code/bespoke/tree/92edcd70b121d13d52fbf6ed2cc1b813205e86ed)
- [SEC MCP 第三方实现](https://github.com/stefanoamorelli/sec-edgar-mcp/tree/88b21ad58c24ad9ab9be21e093d71571457b9057)

