# 来源与查阅范围

论文：Stern 等，Development and characterization of a low-affinity humanized CD19 chimeric antigen receptor for B-cell malignancies，Blood Neoplasia 1(4):100048 (2024)，DOI `10.1016/j.bneo.2024.100048`，PMCID `PMC12182840`，版本 `PMC12182840.1`。

已阅读全文的方法、结果、图注及讨论，检查正文图1–7、方法页的科学符号与指数，并逐页检查官方补充PDF的8页：补充图1–5、表1–3，第6页为空白。参考文献和背景中的其他CAR产品不建立实体。没有使用既往提取结果补充数据。

本次检索日期：2026-10-14。官方补充文件已成功获得，无未解决的资源获取失败。沙箱内首次DNS失败、Europe PMC补充接口随后超时；允许联网后通过PMC云元数据恢复所需内容，不将已恢复资源记为缺失。资源均保存在 `scratch/`：

- 版本发现：`https://pmc-oa-opendata.s3.amazonaws.com/?list-type=2&prefix=PMC12182840.&delimiter=/`，实际列出版本1。
- 身份核对：`https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12182840/fullTextXML`；PMCID、版本、DOI、标题与输入PDF一致。
- 元数据：`https://pmc-oa-opendata.s3.amazonaws.com/PMC12182840.1/PMC12182840.1.json`。
- 补充文件：`https://pmc-oa-opendata.s3.amazonaws.com/PMC12182840.1/BNEO_NEO-2024-000237-mmc1.pdf?md5=69d6006adb7545f63ba0977cd11ae492`，963863字节，MD5一致，已渲染、阅读。
- 图2、3、6：同一云目录下 `BNEO_NEO-2024-000237-gr2.jpg`、`-gr3.jpg`、`-gr6.jpg`，由元数据的真实媒体URL下载并检查。MD5依次为 `16f5e69722c08c5a651a7bb5be8ab382`、`9cec377479f9231b8b482dbca926f7fc`、`cfde7966a9a80c36d4978f96415529ce`，均验证一致；实际像素分别为776×579、767×1335、784×668。其余正文图直接检查输入PDF。
- 超时接口：`https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12182840/supplementaryFiles`；替代路径已获得相同文章的完整补充文件。

# 记录归属与映射决定

以下行号均为最终 `data.jsonl` 的一基物理行号，同时注明表及字段，不依赖会被替换的本地ID。

- `binder`第1–3行分别为FMC63、VH4vκ1、4D5。酵母展示是测量格式，不另建Binder。完整scFv、VH/VL、内部linker序列及CDR编号均未披露，保留为空；补充表1的预测肽不拼接为抗体序列。第2行`germline_origin`保留源文 `IGHVR-30-4*01` 拼写；第3行保留4D5框架及H2移植范围，未据此外推残基或PDB模板。
- `car`第4行`modules`保留共同骨架顺序：IgG4 hinge、10 aa GS连接肽、CH3、CD4跨膜区、4-1BB、CD3ζ。CH3属于IgG4间隔结构，以`hinge`模块保存。T2A分隔的EGFRt是额外共表达蛋白，记录于各组合证据的`car.coexpressed_proteins`，不并入受体模块。
- `manufacturing`第5行保存正文Tn/mem分离、慢病毒导入及明确的14天扩增；三种CAR共用，不因Binder或供者拆分。第6行保存另外明确使用临床级/cGMP慢病毒和制造SOP的IND方案；来源没有充分披露两方案的全部操作一致性，未直接合并，也未把正文14天培养或未知激活条件转抄至该方案。健康供者不自动等于“自体”或“异体”；激活试剂、MOI、培养基、细胞因子等未报告项为空。分析用抗体及巨噬细胞用GM-CSF不写入T细胞制造试剂。
- `abc_combination_db1`第7–9行完成阶段为`in_vivo`；第10行为有明确IND-enabling工作的`preclinical`。获准开展一期试验不等于已完成一期研究；本文没有人体治疗结果。
- `evidence`第11–13行`binder.kd`保存4.8±0.7 nM（SD）、≥8.3 μM、≥45 μM。下界不改为点值，不把酵母展示结果描述为游离scFv测量。浓度系列、缓冲液、检测格式与1:1模型分开记录。第14–16行`binder.tm`保存55±0.7、61±0.9、62±0.6 °C（SD），热处理条件不混入亲和力条件。
- 第17–19行`binder.immunogenicity_ada_risk`保存各Binder的三项肽计数及表1各10条肽的序列、预测分数、IC50和区域，保留表内顺序与重叠肽；IC50是MHC预测值，不是CD19结合Kd，也不是临床ADA结果。
- 第20–22、35–37、40–42行的EGFR/EGFRt读数均是CAR阳性比例，放在`manufacturing.car_positive_ratio`，不填`transduction_efficiency`。代表性流式图与终产品放行测试分别保留；未因数值不同而合并或推定源内冲突。补充表3按HD440/HD536/HD396列序保存，活率、CD3比例、EGFRt比例和WPRE拷贝数同一供者同一测试合在一行。门槛只保留于`raw`，不作为实测结果。
- 第29–31行保存Raji重复刺激实验的原文明示增殖结论和第12天耗竭表型；第32–34行保存另一个补充重复刺激实验的组间比较与第12天表型。没有把Raji实验的4D5增殖结论转移到补充图1。补充图1标题/B面板/正文写NALM6，A图注却写Raji，因此第32–34行`applicable_scenario`不填写靶细胞名称，其他可靠条件保留，并各记一条例外。
- 图6E的纵轴是`%CAR (CD3+CD45+)`，图注称小鼠血液中的CAR T细胞比例；它没有明确说明CAR表达阳性读出及分母，不能将CD3/CD45标记的细胞群百分比直接等同`manufacturing.car_positive_ratio`，也不能转为中位持续时间。经语义回查，未输出该图的百分比估算。图6A接种至治疗为7天，而正文通用方法为5天；图6写5–9只/组，补充图4另写VH4vκ1 N=10；这些动物条件的差异未强行统一。
- CD27/CCR7/CD45RA/CD28单独阳性比例不等于Tcm/Tscm完整门控；只保存来源支持的耗竭标志物表型，不推断记忆亚群比例或功能性耗竭。细胞内IFN-γ阳性率不是释放浓度，CD107a不是杀伤率，残留靶细胞数不转成杀伤百分比，血清和巨噬细胞上清不冒充CAR-T体外释放结果。

# 图像读数与字段边界

已检查所有定量图与图注。最终非空measurement均有明示数字，未输出图像估算。图6E曾作为百分比字段候选检查，并渲染了矢量裁切面板；复核后因CD3/CD45读出的含义及分母不能确认为CAR表达阳性比例而排除。其余无数字标签的图主要是CD107a/细胞内IFN-γ、靶细胞分子密度、残留肿瘤数、血清/巨噬细胞因子、BLI或小鼠生存，没有相应活动measurement字段，不改写为近似的其他指标。扩增与耗竭描述字段可保存原文明示的定性结果，未在字符串中伪造measurement对象。

# 实验与工艺覆盖

“部分覆盖”表示保存了可对应字段的内容，其余读出没有合适的活动字段或保留源内歧义；不把这种情况当作文件未获取。除图像估算外，扩增字符串保存原文明示的定性结论，未把无标签曲线读成精确计数或任意建立时间点结果。

| 清单条目与出处 | 状态 | 输出或缺口 |
|---|---|---|
| 1．三种结合域与人源化，正文第2、4页 | 已覆盖 | binder，第1–3行，name/humanization_level/germline_origin；未披露序列为空 |
| 2．酵母展示与亲和力，图1B–D，第2–4页 | 部分覆盖 | evidence，第11–13行，binder.kd/measurement_method/measurement_conditions；展示格式入applicable_scenario；无表达产量字段 |
| 3．热变性，图1E，第3–4页 | 已覆盖 | evidence，第14–16行，binder.tm/applicable_scenario；温度、时长、体积、试剂及模型 |
| 4．免疫原性预测，补充表1–2，第7页 | 已覆盖 | evidence，第17–19行，binder.immunogenicity_ada_risk；30条肽及九项计数，模型/HLA/预测日期入applicable_scenario |
| 5．共同CAR设计，图2A，第3、5页 | 已覆盖 | car，第4行，modules；各组合证据car.coexpressed_proteins |
| 6．Tn/mem制造与14天培养，第3、5页 | 已覆盖 | manufacturing，第5行，selection_steps/starting_cell_quality/reagents/vector_type/culture_duration |
| 7．代表性CAR表达，图2B | 已覆盖 | evidence，第20–22行，manufacturing.car_positive_ratio；Mock仅作对照，不伪造Binder/CAR实体 |
| 8．四供者表型，图2C | 部分覆盖 | evidence，第23–25行，car.exhaustion_phenotype；无单个CD27等标志物数值字段，不能据此填Tcm/Tscm |
| 9．初始扩增，图3A | 部分覆盖 | evidence，第26–28行，car.expansion_capacity；保存定性比较与0–14天实验范围，无可容纳图像估算对象的数值扩增字段 |
| 10．细胞抗原/配体密度，图3B、5A–B | 未存储 | 靶细胞CD19/CD80/CD86/PD-L1每细胞分子数及患者样本379、397、401、413、418、424、431、440、466、472无对应活动字段；不是Binder亲和力 |
| 11．KG1a/Raji/Nalm6功能，图3C–D | 未存储 | 三CAR、CD107a检测2:1/5小时及IFN-γ细胞内染色1:1/过夜；现有字段无此类阳性率，不能改写为杀伤/释放 |
| 12．Raji重复刺激，图3E–G | 部分覆盖 | evidence，第29–31行，car.expansion_capacity/car.exhaustion_phenotype/applicable_scenario；保留E:T、初始细胞数、加靶/读出日程、重复数；残留肿瘤数不填killing_rate |
| 13．补充重复刺激，补充图1 | 部分覆盖 | evidence，第32–34行，同上；靶名源内冲突置缺，保留n=2、时序及ns；无数值细胞计数字段 |
| 14．Raji WT体内疗效，图4 | 未存储 | NSG，0.5×10^6肿瘤/1×10^6 CAR细胞IV，间隔5天；Mock/FMC63/VH4vκ1/4D5，图注11只/组、两次实验；BLI与小鼠生存无适配字段，不填CAR细胞persistence或杀伤率 |
| 15．NALM6体内疗效，补充图2 | 未存储 | VH4vκ1/4D5/Mock，10只/组、两供者；BLI和小鼠生存无字段。示意图肿瘤剂量1×10^6与正文通用0.5×10^6不同，未将此条件跨实验补写 |
| 16．低CD19 Raji建立，补充图3，第2、8页 | 未存储 | CRISPR KO、PGK100p再表达、两96孔板、1cell/100µL/well、四克隆选克隆4；这是靶细胞构建，不是T细胞manufacturing；克隆4是后续低CD19实验的靶细胞，未建立T细胞制造实体 |
| 17．低抗原体外功能，图5C–D | 未存储 | 三CAR与Raji KO/WT/low各组；两次实验；CD107a/细胞内IFN-γ无适配字段 |
| 18．低抗原动物实验，图6、补充图4 | 未存储 | 三CAR/Mock；BLI、小鼠生存和终点肿瘤CD19密度无字段；图6E的%CAR以CD3/CD45标记，未明确CAR表达阳性读出/分母，不填car_positive_ratio，也不是中位persistence；方法/图示间隔及组样本量的差异见上文 |
| 19．血清–巨噬细胞混合模型，图7 | 未存储 | FMC63/VH4vκ1/Mock，4只/组；D3血清、供者匹配巨噬细胞、5ng/mL GM-CSF培养7天、48小时上清及Luminex；源文含IL-6/GM-CSF等18项热图，其血清及巨噬细胞来源不属于CAR-T制造功能释放字段 |
| 20．临床级IND制造，第10页、补充图5 | 已覆盖 | manufacturing，第6行，name/selection_steps/starting_cell_quality/reagents/vector_type；abc_combination_db1，第10行，completed_experiment_phase |
| 21．临床级三供者表达，补充图5A | 已覆盖 | evidence，第35–37行，manufacturing.car_positive_ratio；59.32%、47.80%、52.57%，不和表3代表不同测试的读数合并 |
| 22．临床级扩增/群体表型，补充图5B–C | 部分覆盖 | evidence，第38–39行，car.exhaustion_phenotype/car.expansion_capacity；原文定性、各供者Mock比较和截至第14天范围；没有由此推定工艺总时长 |
| 23．临床级功能，补充图5D | 未存储 | KG1a/LCL OKT3/LCL的CD107a及细胞内IFN-γ无字段；图注另提CD19low但没有相应柱，不虚构额外组结果 |
| 24．三供者放行，补充表3，第8页 | 部分覆盖 | evidence，第40–42行，manufacturing.cell_viability/cd3_positive_ratio/car_positive_ratio/vcn；按供者分行，同次测试合并；VSV-G的0.2/0.2/0.00 copies/50ng genomic DNA及残珠24/10/14无对应字段，不替代VCN |
| 25．临床转化阶段，第10–11页 | 已覆盖 | abc_combination_db1，第10行，completed_experiment_phase=preclinical；IND30031、IRB23328是试验获准信息，未生成临床结果 |

# 核对与验证状态

已完成单代理全文提取、自行回查原文、覆盖复核和语义复核；按本次要求禁用子代理，没有独立多代理交叉核对。检查了亲和力与展示格式、SD/SEM、外键、测量阶段、组别与门控、比较符、抗体/受体/工艺边界和源内冲突。

已运行项目 `cart_db.agent_output.prepare_output` 的只读校验，另检查活动字段、嵌套形状、类型、枚举、measurement成员、正值/百分比约束、非空本地标签、先实体后引用的顺序、ABC与证据外键一致性及来源。校验产生的UUID/单位归一化结果没有写回本文件；最终UUID替换、可空字段补齐、字段排序和单位归一化由runner负责，其发布结果尚未在本次验证。

最终文件：`data.jsonl`共42行，其中binder 3、car 1、manufacturing 2、abc_combination_db1 4、evidence 32。`error_log.jsonl`有3条例外，分别对应三行补充重复刺激靶名歧义。未报告的可空字段保持为空；普通未报告项和没有活动字段的读出不记为异常。所有暂存文件与下载材料均位于本输出目录的`scratch/`，仅上述数据、例外日志及本说明作为最终发布文件。
