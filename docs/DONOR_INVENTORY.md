# Donor 样本清单

生成于 2026-09-22 14:34。共 62 位作者、3859 条帖子。

本文件由 `ml/donor_report.py` 生成，**不要手改**。
每个数字都来自闸门本身使用的同一批函数（`content.tells.sentence_variation`、
`live.style.build_target`、`ml_experiments/authorship_v2.json`），
所以这份报告不会和管线对同一位 donor 给出不同的数。

## 四个账号的语言 donor

| 账号 | donor | 帖数 | 可测句长 | 可分辨性 | 缺什么 |
| --- | --- | --- | --- | --- | --- |
| zh_macro | qinbafrank | 403 | 372 | usable | — |
| en_macro | globalmktobserv | 96 | 28 | usable | 可测句长 28 < 30；闸门特征零宽区间: fragment_rate |
| zh_industry | michael_qqq2025 | 285 | 204 | usable | 闸门特征零宽区间: long_argument_rate |
| en_industry | aleabitoreddit | 524 | 462 | usable | — |

判定门槛：帖数 ≥ 60（`live/style.py MIN_POSTS`）、可测句长帖 ≥ 30
（`MIN_POSTS_FOR_CV_BAND`）、可分辨性来自 authorship 五组基线。

## 全部作者

| 作者 | 语种 | 帖数 | 可测句长 | CV p10/中位/p90 | 数字密度 中位/p90 | 风格区间 | 可分辨性 | 采集列表 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| aleabitoreddit ★ | en | 524 | 462 | 0.315/0.499/0.79 | 0.333/0.625 | 可用 | usable | x_accounts |
| qinbafrank ★ | zh | 403 | 372 | 0.433/0.58/0.716 | 0.448/0.7 | 可用 | usable | x_accounts |
| michael_qqq2025 ★ | zh | 285 | 204 | 0.372/0.516/0.732 | 0.4/0.714 | 可用 ⚠闸门零宽:long_argument_rate | usable | x_accounts |
| globalmktobserv ★ | en | 96 | 28 | 0.269/0.843/0.979 | 0.444/0.783 | 可用 ⚠闸门零宽:fragment_rate | usable | x_accounts |
| phyrexni | zh | 453 | 357 | 0.288/0.455/0.624 | 0.4/0.857 | 可用 | usable | x_accounts |
| beth_kindig | en | 138 | 10 | 0.778/1.034/1.495 | 0.4/0.8 | 可用 | usable | x_accounts |
| xingpt | zh | 121 | 88 | 0.318/0.532/0.667 | 0.379/0.667 | 可用 | undetermined | x_accounts |
| kovainvest | zh | 113 | 97 | 0.309/0.497/0.73 | 0.286/0.6 | 可用 ⚠闸门零宽:long_argument_rate | usable | x_accounts |
| RaoulGMI | en | 66 | 49 | 0.413/0.585/0.946 | 0.143/0.375 | 可用 | usable | learning |
| JimMarous | en | 59 | 59 | 0.433/0.525/0.717 | 0.125/0.273 | 可用 | usable | learning |
| EricBalchunas | en | 59 | 20 | 0.485/0.829/1.151 | 0.333/0.6 | 可用 | usable | learning |
| Convertbond | en | 58 | 26 | 0.509/0.717/1.091 | 0.5/0.833 | 可用 | undetermined | learning |
| JeffSnider_EDU | en | 58 | 48 | 0.443/0.624/0.897 | 0.167/0.5 | 可用 | not evaluated | learning |
| garyblack00 | en | 51 | 37 | 0.35/0.529/0.738 | 0.429/0.833 | 可用 | not evaluated | learning |
| BobEUnlimited | en | 49 | 17 | 0.717/0.945/1.339 | 0.2/0.6 | 可用 | not evaluated | learning |
| citrini | en | 48 | 13 | 0.413/0.503/0.897 | 0.143/0.4 | 可用 | undetermined | x_accounts |
| jturek18 | en | 48 | 2 | 0.362/0.811/0.811 | 0.2/0.2 | 可用 ⚠闸门零宽:fragment_rate | not evaluated | learning |
| jasongoepfert | en | 47 | 28 | 0.639/0.923/1.159 | 0.4/0.8 | 可用 | not evaluated | learning |
| leadlagreport | en | 46 | 19 | 0.638/0.837/1.027 | 0.4/0.8 | 可用 | not evaluated | learning |
| choffstein | en | 44 | 21 | 0.384/0.71/0.942 | 0.5/0.6 | 可用 | not evaluated | learning |
| DeepSailCapital | en | 43 | 11 | 0.43/0.571/1.069 | 0.533/0.8 | 可用 | usable | learning |
| efipm | en | 43 | 21 | 0.535/0.855/1.126 | 0.4/0.6 | 可用 | not evaluated | learning |
| patrick_oshag | en | 41 | 32 | 0.319/0.526/0.864 | 0.133/0.462 | 可用 | not evaluated | learning |
| harmongreg | en | 41 | 1 | 0.74/0.74/0.74 | 0.2/0.2 | 可用 | not evaluated | learning |
| tradexwhisperer | en | 39 | 36 | 0.509/0.746/0.994 | 0.375/0.667 | 可用 | not evaluated | x_accounts |
| natbrunell | en | 39 | 28 | 0.496/0.853/1.046 | 0.286/0.571 | 可用 | not evaluated | learning |
| awealthofcs | en | 39 | 28 | 0.456/0.749/0.955 | 0.4/0.875 | 可用 | not evaluated | learning |
| tseides | en | 39 | 16 | 0.596/0.94/1.363 | 0.2/0.4 | 可用 | not evaluated | learning |
| StockJabber | en | 37 | 19 | 0.38/0.803/1.176 | 0.143/0.333 | 可用 | not evaluated | learning |
| RyanDetrick | en | 36 | 11 | 0.713/0.924/1.158 | 0.2/0.5 | 可用 | not evaluated | learning |
| WarrenPies | en | 36 | 21 | 0.409/0.696/0.884 | 0.4/0.667 | 可用 ⚠闸门零宽:long_argument_rate | not evaluated | learning |
| KrisAbdelmessih | en | 35 | 8 | 0.371/0.746/1.072 | 0.222/0.4 | 可用 | not evaluated | learning |
| TaviCosta | en | 35 | 32 | 0.723/0.866/1.274 | 0.25/0.4 | 可用 | not evaluated | learning |
| DavidTaggart | en | 34 | 5 | 0.541/0.954/1.25 | 0.167/0.6 | 可用 | not evaluated | learning |
| ericjackson | en | 31 | 19 | 0.358/0.655/0.909 | 0.333/0.667 | 可用 | not evaluated | x_accounts |
| investmattallen | en | 31 | 9 | 0.304/0.693/0.862 | 0.4/0.6 | 可用 | not evaluated | learning |
| AndrewThrasher | en | 31 | 6 | 0.459/0.816/1.002 | 0.6/0.8 | 可用 | not evaluated | learning |
| BullandBaird | en | 30 | 5 | 0.363/0.732/0.969 | 0.167/0.6 | 可用 | not evaluated | learning |
| josephwang | en | 29 | 8 | 0.484/0.738/0.844 | 0.2/0.333 | 可用 | not evaluated | learning |
| morganhousel | en | 29 | 16 | 0.759/1.011/1.289 | 0.4/0.5 | 可用 | not evaluated | learning |
| TheAlphaThought | en | 27 | 12 | 0.278/0.672/0.982 | 0.333/0.714 | 可用 | not evaluated | learning |
| sytaylor | en | 26 | 16 | 0.42/0.579/0.682 | 0.235/0.5 | 可用 | not evaluated | learning |
| MebFaber | en | 25 | 17 | 0.334/0.685/1.101 | 0.222/0.55 | 可用 | not evaluated | learning |
| callieabost | en | 25 | 5 | 0.691/0.864/1.005 | 0.2/0.429 | 可用 | not evaluated | learning |
| JSeyff | en | 23 | 9 | 0.666/0.82/1.204 | 0.4/0.6 | 不可用 | not evaluated | learning |
| jameslavish | en | 23 | 7 | 0.486/0.68/1.467 | 0.2/0.4 | 不可用 | not evaluated | learning |
| borrowed_ideas | en | 22 | 7 | 0.524/1.09/1.504 | 0.2/0.6 | 不可用 | not evaluated | learning |
| GeorgeGammon | en | 22 | 5 | 0.211/0.484/0.687 | 0.4/0.8 | 不可用 | not evaluated | learning |
| MaxfieldOnBanks | en | 22 | 6 | 0.296/0.69/1.298 | 0.091/0.2 | 不可用 | not evaluated | learning |
| dailydirtnap | en | 22 | 7 | 0.558/0.866/1.208 | 0.2/0.333 | 不可用 | not evaluated | learning |
| jasonhenrichs | en | 18 | 0 | — | — | 不可用 | not evaluated | learning |
| AndreasSteno | en | 17 | 5 | 0.456/0.512/0.756 | 0.0/0.25 | 不可用 | not evaluated | learning |
| mikulaja | en | 16 | 5 | 0.399/0.44/0.639 | 0.444/0.545 | 不可用 | not evaluated | learning |
| pboockvar | en | 15 | 6 | 0.471/0.628/0.708 | 0.4/0.6 | 不可用 | not evaluated | learning |
| MarcRuby | en | 15 | 3 | 0.785/0.904/0.915 | 0.6/0.6 | 不可用 | not evaluated | learning |
| NikMilanovic | en | 13 | 12 | 0.513/0.665/0.86 | 0.375/0.6 | 不可用 | not evaluated | learning |
| rjccapital | en | 12 | 5 | 0.542/0.62/0.876 | 0.429/0.6 | 不可用 | not evaluated | x_accounts |
| michaelbatnick | en | 11 | 5 | 0.559/0.83/1.408 | 0.5/0.6 | 不可用 | not evaluated | learning |
| charliebilello | en | 10 | 7 | 0.126/0.688/0.99 | 0.4/1.0 | 不可用 | not evaluated | learning |
| LynAldenContact | en | 8 | 1 | 0.862/0.862/0.862 | 0.6/0.6 | 不可用 | not evaluated | learning |
| jam_croissant | en | 2 | 2 | 0.569/0.694/0.694 | 0.545/0.545 | 不可用 | not evaluated | learning |
| Ritholtz | en | 1 | 0 | — | — | 不可用 | not evaluated | learning |

★ = 已指派给某个账号作为语言 donor。

## 可替换的候选

可分辨性评估判定为 usable、且尚未被指派的作者：

- **phyrexni**（zh，453 帖，可测句长 357，recall 0.7647）
- **beth_kindig**（en，138 帖，可测句长 10，recall 0.9286）
- **kovainvest**（zh，113 帖，可测句长 97，recall 0.7429）
- **RaoulGMI**（en，66 帖，可测句长 49，recall 0.6）
- **JimMarous**（en，59 帖，可测句长 59，recall 1.0）
- **EricBalchunas**（en，59 帖，可测句长 20，recall 0.7692）
- **DeepSailCapital**（en，43 帖，可测句长 11，recall 0.5）

## 这份清单的局限

- 可分辨性只说明**这些作者彼此之间**能否区分，不说明某个生成出来的人设是否可辨认。
- 样本量门槛是本项目自己设的，不是统计学意义上的充分性证明。
- 未进入评估的作者是**证据缺失**，不是证据表明不可用；补足样本后需重跑。
- 所有数字随语料增长而变化，采集之后应重新生成本文件。
- 只有**被闸门使用的**特征零宽才会挡稿；`conclusion_opener` 对全部 62 位作者都是零宽，
  那是因为真人几乎不用结论式开头，不是缺陷，故不计入「缺什么」。
