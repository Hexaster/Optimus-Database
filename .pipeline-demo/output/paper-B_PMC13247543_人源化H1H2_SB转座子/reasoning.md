# 证据与决策摘要

## 来源与执行范围

来源为 Andrade 等《Development and in vivo evaluation of novel humanized CD19 CAR-T cells for advanced B cell malignancies》，Frontiers in Immunology 17:1798748，DOI `10.3389/fimmu.2026.1798748`，PMC13247543，发表于2026-05-26。已阅读所给18页 PDF 的正文、方法、结果、讨论、主图1–7和表1，并检查同篇补充 PDF 全部12页：图S1–S9、表S1/S2及补充模拟方法。参考文献与致谢不作实体来源。

本次应用 `.claude/skills/extract-cart-data/SKILL.md`，先读取全部5份 YAML。按要求单代理完成全文抽取、覆盖复查与原文语义复查；未启用子代理或独立代理交叉核对。所有下载、渲染、临时清单与脚本均位于本目录的 `scratch/`，不属于发布文件。下文“行”均指最终 `data.jsonl` 从1开始的全文件物理行号，结合表名和字段定位，不使用将被替换的本地ID。

### 补充材料恢复

检索日期为2026-10-14。先检查本地 `data/CD19`，未发现配套补充文件。受限网络首次请求出现DNS错误；取得网络访问后，依次检查下列实际资源：

- PMC对象前缀清单：`https://pmc-oa-opendata.s3.amazonaws.com/?list-type=2&prefix=PMC13247543.&delimiter=/`，返回唯一版本 `PMC13247543.1/`。
- 元数据：`https://pmc-oa-opendata.s3.amazonaws.com/PMC13247543.1/PMC13247543.1.json`，核对PMCID、DOI与论文题名一致。
- 补充PDF：`https://pmc-oa-opendata.s3.amazonaws.com/PMC13247543.1/DataSheet1.pdf`，来自上述 `media_urls`；1526843字节，MD5 `a0b411ea55b8c30e4fab5e77f5f429b8` 与元数据相符，文件可打开，已实际阅读文字和图像。
- 出版社正文页：`https://www.frontiersin.org/articles/10.3389/fimmu.2026.1798748/full#supplementary-material`，成功取得同篇正文。Europe PMC的 `https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13247543/supplementaryFiles` 发生读取超时；PMC元数据所列XML下载出现TLS EOF。已用所给完整正文PDF和成功恢复的补充PDF覆盖相关内容，不将这些访问失败记作仍缺失的源材料。

主图像直接从原始PDF提取，补充图S8从补充PDF提取原始嵌入图像；已查看主图1–7、全部补充页及用于精读的原图裁切。未使用其他文档或历史抽取结果补值。

## 实体与字段归属

- `binder` 第1–4行分别为FMC63、图2B中的人源化H1前体、最终harmonized H1和H2。H1前体与最终H1之间有原文明示的回突变，保留为不同结合域；前体只关联自身TANGO计算，不生成其CAR组合。最终H1/H2共享人源化VL，但VH不同。正文和补充材料未给完整氨基酸序列，序列字段为空；仅将明示的 `(GGGGS)3` 按重复记为 `GGGGSGGGGSGGGGS`。图2A的57%/64%为VH间比较，未放入 `germline_origin_identity`，也未推测胚系基因号或CDR编号体系。
- `car` 第5行共用19BBz骨架，`modules` 按N端c-Myc、CD8 spacer、CD8跨膜区、4-1BB、CD3 zeta排列（2.4、2.9、图3A图注）。不把Binder、FvFc的Fc区域或SB100X加入骨架模块。
- `manufacturing` 第6行为三种CAR共用的SB方案；保留PBMC回收/分离/清洗顺序、试剂量、激活时序、初始与后续培养基、IL-2及8天培养。电转发生在TransAct激活之前，未将“2小时后激活”写成“激活后2小时转染”。健康供者身份不足以判定“自体/异体”，故 `t_cell_source` 为空。未把肿瘤细胞CRISPR编辑、CHO蛋白生产、流式染色或动物输注条件转入该制造工艺。
- `manufacturing` 第7行为原文明示的Mock电转且未转染对照流程（图5、图7、S9图注），与SB导入CAR不同；只保留明确的电转/未转染身份，不复制未对照组单独说明的质粒、培养或激活参数。该对照有图3A、图4、图5/S9的实测信息，不为其虚构Binder、CAR或ABC组合。
- `abc_combination_db1` 第8–10行对应FMC63、最终H1、H2，均关联同一骨架与同一SB方案；阶段为 `in_vivo`，研究性异种移植实验不标作IND支持研究或人体临床。
- `evidence` 第15–17行的 `binder.kd/kon/koff` 全部属于可溶性FvFc、1:2二价分析物模型，不解释成游离单价scFv亲和力。H1保留正文15.19 nM，并在 `raw` 同时保留图示15.2 nM的舍入表述。Fc融合不另建Binder，也不作为别名。
- 第33–39行的抗c-Myc阳性率写入 `manufacturing.car_positive_ratio`，不写入 `transduction_efficiency`；代表性流式百分比与八供者汇总均值分开。第40–51行的记忆分群写入 `car.*_ratio`，因为比较对象为不同构型；不再向制造字段复制。TEMRA未改写为Teff，产品CD4/CD8组成未冒充起始细胞比。
- 不由细胞存活数推导杀伤率，不由小鼠生存期推导CAR-T中位可检出时长，不由肿瘤光子通量推导CAR-T扩增量。相关无活跃字段的结果不强行塞入其他字段。

## 覆盖核对

| 实验、流程或实体及位置 | 覆盖结论 | 最终位置或缺口 |
|---|---|---|
| Binder人源化与harmonization，2.4、3.1、图2A/B | 已覆盖 | binder第1–4行 `humanization_level/germline_origin/linker`；evidence第11–14行 `binder.aggregation_tendency`；仅前体计算不外推功能 |
| 可溶性FvFc表达与纯化，2.4 | 部分覆盖 | evidence第15–26行保留FvFc测量格式；ExpiCHO表达10天、Protein A/SEC、SDS-PAGE/Western流程没有相应活跃实体字段，未转为T细胞制造参数；载体pcDNA 3.4/4.3的正文差异不用于Binder别名 |
| BLI结合动力学，2.6、图2D、S3 | 已覆盖，保留源冲突 | evidence第15–17行 `binder.kd/kon/koff/measurement_conditions`，浓度、单位问题见异常说明 |
| Raji同源靶细胞结合，2.5、图2E | 部分覆盖 | evidence第18–23行 `binder.species_reactivity/applicable_scenario`，分别保留5/50 nM条件；阳性率依FMC63/H1/H2顺序为5 nM时95.6/94.4/77.9%，50 nM时98.9/95.3/90.1%；同源抗原结合率及MFI没有活跃结果字段，未误记为交叉反应率或EC50 |
| Jurkat非特异性结合对照，2.5、3.1 | 已覆盖 | evidence第24–26行 `binder.cross_reactivity_cell`，50 nM、相当于二抗对照，未把“未检出差异”改为0% |
| MD、RMSD与MM/PBSA，2.7、3.2、表1、补充方法/S4–S7 | 部分覆盖 | binder第1/3/4行 `structure_template` 保留7URV；已检查三组各三次500 ns模拟、表1九项自由能及S4–S7。RMSD、结合自由能和模拟体系组成无活跃字段，未当作Kd、Tm或实测聚集率 |
| HLA呈递预测，2.8、图2C、S2、表S1 | 已覆盖至可用字段 | evidence第27–29行 `binder.immunogenicity_ada_risk`；`applicable_scenario` 保留9/15-mer、模型版本、阈值及表S1的40行等位基因原顺序；未将预测当作临床ADA |
| 健康供者PBMC与SB制造，2.2、2.9、3.3 | 已覆盖 | manufacturing第6行 `selection_steps/reagents/activation_method/culture_system/cytokine_combination/culture_duration`；evidence第30–32行来源与产品关联；Mock见manufacturing第7行 |
| day8 CAR表达，图3A | 已覆盖 | evidence第33–36行代表图 `manufacturing.car_positive_ratio`；第37–39行为八供者柱均值的图像范围；仅c-Myc阳性读数，不存为CD3比例 |
| 产品CD4/CD8组成，3.3、图3A | 未存储数值 | 末端产品CD4/CD8组成没有相应活跃字段；不写入制造起始 `cd4_cd8_ratio` |
| day8 CD69/CD25/HLA-DR，3.3、图3B–D、讨论 | 部分覆盖 | evidence第52–54行 `car.activation_readout/tonic_signaling_tendency`；后者明确为作者对静息表型的解释。表达百分比和MFI无对应活跃量化字段，未编造激活峰时点 |
| day8记忆分化，图3E | 部分覆盖 | evidence第40–45行代表性CD4/CD8门控，46–51行汇总柱段 `car.tscm_ratio/tcm_ratio/tem_ratio`；不存Naive/TEMRA为别的亚型；下排汇总图分母标签矛盾已随数据保留 |
| 长期细胞毒性，2.11、3.4、图4 | 部分覆盖 | evidence第55–86行 `manufacturing.killing_activity`：CD19WT/CD19Low、1/0.5/0.25/0.1 E:T、Mock与三种CAR、96 h、0/24/48/72/96 h采样及检测方法；仅生成实际报告的分组。剩余GFP+细胞数及AUC无活跃结果字段，因此 `killing_rate` 为空，不从曲线另算百分比 |
| 24 h细胞因子，2.12、3.4、S8 | 已覆盖 | evidence第87–92行，按两种靶细胞和三种CAR分组；每组IL-2、TNF-α、IFN-γ合为一条。`manufacturing.ifn_gamma_release/cytokine_release` 为图像范围；保留单供者、三重复、样品处理和ELISA条件。图S8未明确E:T，未套用图4的四种比例 |
| 抗原刺激耗竭表型，3.5、图5、S9 | 已覆盖至可用字段 | evidence第93–108行，CD4/CD8、0/96 h、Mock/三CAR均保留；`car.exhaustion_phenotype` 或Mock的 `manufacturing.exhaustion_phenotype` 保留标志物组合、变化方向与原文明示比例（H2 CD8 LAG-3为72%、三阳35%；Mock CD8三阳9.2%→4.3%）。未把无标签柱图读数伪装为精确百分比 |
| 标准CD19WT小鼠模型，2.13、3.6、图6 | 部分覆盖 | evidence第109–111行 `applicable_scenario` 与组合阶段：雌NSG、8–12周、每组5只、肿瘤1×10^5、day2给7×10^5 CAR+（总T细胞6.8×10^6）、PBS对照及监测。肿瘤光通量、生存曲线、伦理终点和疑似异种GVHD无对应活跃结果字段；未写成CAR持久性 |
| 进展期CD19Low小鼠模型，2.13、3.6、图7 | 部分覆盖 | evidence第112–114行 `applicable_scenario`：day11给1×10^6 CAR+（总T细胞7×10^6）、每组初始5只、PBS/Mock对照；保留H2有1只输注后24 h内原因不明死亡。存活至day32/36等不是CAR可检出时长；未转填 `car.persistence` |

未列入活跃字段的原文读数属于当前字段范围之外，不作为另一字段的缺失异常。主图与补充图中的方法、门控、统计单位和对照已回源核对；未把没有精确数字等同于没有实验。

## 图像估算的可追溯性

所有坐标以原始图像左上角为原点，单位为像素，无缩放坐标或插值生成的额外时间点。图2/图3使用PDF内原始图像：`fig-page-7.png`为1876×2770，`fig-page-9.png`为2360×3740；S8为补充PDF第11页嵌入图 `supp-11-embedded-0.png`，724×1226。检查裁切图仅帮助阅读，以下坐标均已落回完整原图。

线性轴使用 `v(y)=v0+(y-y0)*(v1-v0)/(y1-y0)`。点/柱边缘的像素区间包含线宽与定位精度；向外取整。TANGO按1个原图单位、CAR阳性率按0.1个百分点、细胞因子按1 pg/mL取整。记忆堆叠柱分别读取每段上下边界，每边允许±2像素，以段高度计算比例后向外取整至1个百分点；不读取累计高度为单亚型比例。所有结果为 `kind: image_estimated_range`，`value/error` 为空；范围仅表示读图精度，不代表SD、SEM或生物变异。

### 坐标校准

| 校准代号 | 图像与两处实际刻度 |
|---|---|
| A1/A2/A3/A4 | 图2B四幅：FMC63 y=919→0、645→100；H1前体927→0、645→100；最终H1 935→0、645→100；H2 924→0、641→100。原图未标单位，不填% |
| B | 图3A阳性率均值：y=389→0%、51→40% |
| C上/C下 | 图3E上排y=2939→0%、2876→20%；下排3691→0%、3627→20%。段宽/段高取自各产品自身柱体，避开中心误差棒 |
| D1/D2/D3 | S8A IL-2 y=305→0、67→200；S8B TNF-α 710→0、472→200；S8C IFN-γ 1114→0、876→200，单位均为pg/mL |

### 读数定位及最终字段

下表“记忆三项”按 `car.tscm_ratio / car.tcm_ratio / car.tem_ratio` 顺序；“因子三项”按 `manufacturing.cytokine_release[0].concentration`（IL-2）、`[1].concentration`（TNF-α）、`manufacturing.ifn_gamma_release` 顺序。三项放在同一条件行，未把三个读出拆成三个实验。

| evidence物理行与字段 | 校准、读数像素区间或段边界 | 最终估算范围 |
|---|---|---|
| 第11行 binder.aggregation_tendency[0].value；VH位点50 | x=185，y=835–839 | 29–31 原图单位未注明 |
| 第12行 binder.aggregation_tendency[0].value；VH位点50 | x=665，y=697–701 | 80–82 原图单位未注明 |
| 第13行 binder.aggregation_tendency[0].value；VH位点80 | x=1237，y=815–819 | 40–42 原图单位未注明 |
| 第14行 binder.aggregation_tendency[0].value；VH位点50 | x=1620，y=792–796 | 45–47 原图单位未注明 |
| 第37行 manufacturing.car_positive_ratio | x=879，y=229–233 | 18.4–19.0 % |
| 第38行 manufacturing.car_positive_ratio | x=949，y=239–243 | 17.2–17.8 % |
| 第39行 manufacturing.car_positive_ratio | x=1018，y=230–234 | 18.3–18.9 % |
| 第46行 记忆三项 | C上，各段y上→下：2859→2876；2752→2856；2626→2752 | 4–7% / 31–35% / 38–42% |
| 第47行 记忆三项 | C上，各段y上→下：2861→2879；2753→2855；2639→2753 | 4–7% / 31–34% / 34–38% |
| 第48行 记忆三项 | C上，各段y上→下：2861→2873；2759→2856；2637→2759 | 2–6% / 29–33% / 37–40% |
| 第49行 记忆三项 | C下，各段y上→下：3594→3618；3497→3590；3383→3497 | 6–9% / 27–31% / 34–37% |
| 第50行 记忆三项 | C下，各段y上→下：3585→3611；3489→3578；3389→3489 | 6–10% / 26–30% / 30–33% |
| 第51行 记忆三项 | C下，各段y上→下：3578→3600；3483→3573；3385→3483 | 5–9% / 26–30% / 29–32% |
| 第87行 因子三项 | D1/D2/D3，x=159，各项y区间：210–214；614–618；999–1003 | 76–80 / 77–81 / 93–97 pg/mL |
| 第88行 因子三项 | D1/D2/D3，x=226，各项y区间：200–204；603–607；942–946 | 84–89 / 86–90 / 141–145 pg/mL |
| 第89行 因子三项 | D1/D2/D3，x=294，各项y区间：182–186；596–600；985–989 | 100–104 / 92–96 / 105–109 pg/mL |
| 第90行 因子三项 | D1/D2/D3，x=362，各项y区间：233–237；625–629；1029–1033 | 57–61 / 68–72 / 68–72 pg/mL |
| 第91行 因子三项 | D1/D2/D3，x=428，各项y区间：216–220；617–621；1010–1014 | 71–75 / 74–79 / 84–88 pg/mL |
| 第92行 因子三项 | D1/D2/D3，x=495，各项y区间：182–186；592–596；987–991 | 100–104 / 95–100 / 103–107 pg/mL |

图2B仅抽取清晰残基位置处的局部TANGO曲线纵坐标，未把局部高峰称作整分子的总聚集评分。图3E的代表性门控明示百分比保留原值，汇总堆叠柱为不同统计层级；两者未互换。S8只估计柱的中心结果，未估计误差项；也未自行撤销样品1:1稀释以产生新浓度。

## 异常与最终验证

当前 `error_log.jsonl` 共9条，均带具体中文 `message`：

- evidence第15–17行：方法段分析物最低浓度1.17 nM，而S3实际列出的五条曲线最低2.34 nM；列表保留可见曲线的原顺序，适用范围同时保留正文范围，不虚构第六条曲线。
- evidence第15–17行：图2D的Koff表头实际印作 `10^3 1/s`，与同表Kd/Kon数量级不相容。保留原数字与印刷单位，不自行补负号；下游应按异常标记复核，不能直接把这些印刷单位当作已校正物理速率。
- evidence第49–51行：图3E下排邻接流式门控为CD8+，汇总柱轴却写CD4+；保留两种原始标签及柱段读数，不强行确认其分母。代表性CD8+流式数据第43–45行另有清楚门控，不受此歧义影响。

已经完成JSONL逐行解析、活跃字段/对象形状/类型/枚举/必填项与来源检查，验证ID非空、唯一、先定义后引用、ABC与证据三方关联一致、仅填写具备实体外键的归属字段。项目 `cart_db.agent_output.prepare_output()` 在内存中校验通过，未将其生成的UUID或归一化副本写回候选文件。另行复查了百分比边界、非负参数、比较形式、测量kind的数值成员和图像范围下限小于上限。覆盖复查和语义复查均已完成；未声称完成独立代理交叉核对。

候选最终共114行：binder 4、car 1、manufacturing 2、abc_combination_db1 3、evidence 104。三份发布文件直接位于指定暂存目录。UUID替换、可空字段补齐和最终单位归一化由运行器执行，目前候选文件保留来源数值和单位，发布结果尚待运行器处理。
