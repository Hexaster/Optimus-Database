# 证据与提取决策摘要

## 来源与读取范围

来源为 Nasiri 等的 *T-cells engineered with a novel VHH-based chimeric antigen receptor against CD19 exhibit comparable tumoricidal efficacy to their FMC63-based counterparts*，Frontiers in Immunology，2023-02-16，DOI `10.3389/fimmu.2023.1063838`；本次指定文献标识为 `PMC9978144`。已读取所给 PDF 全部13页，提取范围为摘要、正文、方法、结果、讨论中本研究自身的数据和限制；参考文献及讨论中的其他研究不作为本研究数据。

已实际查看第3、4页方法页面，以及第5–10页图1–6的全部内嵌原图与图注。原图尺寸依次为3829×3000、2534×3335、3821×2054、3808×4304、3843×2501、3815×1937像素。第4页图像确认 polybrene 为 `6 µg/mL`，CFSE 为 `1 µL of 5 mM CFSE per mL of PBS`，mitomycin C 为 `50 µL of 1 mg/mL`；PDF文字层把若干 `µ` 提取成 `m`，已按可读页面正确抄录，无残留未辨识字符。

2026-10-14尝试以下资源入口，均因 DNS 解析失败未取得网页或附件：

- PMC云对象列表：`https://pmc-oa-opendata.s3.amazonaws.com/?list-type=2&prefix=PMC9978144.&delimiter=/`
- Europe PMC全文：`https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9978144/fullTextXML`
- Europe PMC补充材料：`https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9978144/supplementaryFiles`
- PDF实际链接的出版页面：`https://www.frontiersin.org/articles/10.3389/fimmu.2023.1063838/full`

正文中的六幅图已完整取得并查看。第12页数据可用性声明含通用的“article/supplementary material”措辞，未指出具体补充文件名、补充图号或序列附件；本次未取得额外附件，无法核实在线附件清单。未把正文未报告的结合域序列或亲和力臆定为“附件中存在但不可读”。

## 实体、条件与字段映射

下文行号均指最终 `data.jsonl` 的一基物理行号，按表名、行号与字段定位，不使用待替换的本地ID。

- `binder` 第1、2行分别为本文使用的 `CD19-specific VHH` 与 `FMC63`。前者在第10页明确来自骆驼科重链抗体，`humanization_level=non_human`；FMC63在本文未明确说明人源化状态，留空。未提供可抄录的结合域氨基酸序列，不从引物、引用文献或名称补齐。`evidence` 第19行 `binder.immunogenicity_ada_risk` 仅记录作者提出的潜在限制，不当作实测ADA结果。
- 第3页2.2明确两构建体除识别域外相同，因此共享 `car` 第3行。`modules` 仅存原文明确分类并依次出现的4-1BB共刺激域和CD3ζ信号域；CD8α保留于 `name`，因未明确区分铰链与跨膜区而不臆造模块，记入异常日志。无模块序列或长度推断。
- `manufacturing` 第4–8行依原文MOI顺序1、5、10、15、25区分五种实际测试工艺；同一MOI下两种CAR共享操作流程，不按Binder、供者或结果另拆工艺。`abc_combination_db1` 第9–18行按每个MOI先VHH、后FMC63关联10个真实实验组合，`completed_experiment_phase=in_vitro`；第12页明确动物验证属于未来研究。
- `manufacturing` 第4–8行保留健康供者全血至PBMC的Ficoll步骤、PBS比例、800×g/20分钟/室温/两次洗涤，CD3/CD28磁珠及2:1比例，3天激活，第三代慢病毒，6 µg/mL polybrene，完整RPMI 1640加10% FBS，以及转导后6–8天移珠。`cytokine_combination` 和相关 `reagents.amount.raw` 按来源保留初始培养50 IU/mL IL-2、3天激活100 IU/mL、之后每周三次50 IU/mL三个阶段；没有合成为50–100的浓度范围。离心转导的60分钟、1200×g、25°C在 `evidence` 第20–29行 `applicable_scenario` 保留。总培养时长与病毒完整接触时长未报告，`culture_duration`、`contact_duration` 留空；6–8天移珠不是总培养时长。健康供者体外研究没有对应受者，不据此填“自体”或“异体”。
- HEK293T包装时的PEI、DMEM、包装质粒、病毒-80°C保存和滴定时8 µg/mL polybrene不转移到T细胞制造字段。本文没有T细胞冻存工艺；病毒qPCR滴定也不是成品T细胞VCN。
- `evidence` 第20–31行中的CAR表面表达百分比进入 `manufacturing.car_positive_ratio`，不再复制到 `manufacturing.transduction_efficiency`。图2A逐MOI代表性读数与图3C–D最终表征分别保留，后者为59.4%和60.8%，不将第7页约59%/60%的重复叙述再算为独立实验。
- `evidence` 第32–39行在 `car.expansion_capacity` 保存图4A的72小时CFSE增殖百分比及明确标注的对应CAR阴性对照值，未将百分比改为扩增倍数。四种培养条件依图顺序为单培养、K562、Ramos、Raji。对照没有Binder或CAR，不创建虚构的A/B实体。
- `evidence` 第40–66行逐靶细胞、E:T和效应细胞保存图5A的27个明示PI阳性靶细胞百分比。`manufacturing.killing_activity` 保留CFSE阳性靶细胞门控、16小时和3:1/6:1/10:1。数值是源图代表性靶细胞死亡比例，不自行扣减背景；K562的非零死亡不改成“无杀伤”。图5A上方靶细胞单独培养的PI阳性基线依次为K562 9.13%、Raji 6.12%、Ramos 14.3%，仅作为读图背景。图5B标为重复实验均值±SD，与代表性直方图的报告层次不同；已有明示值时未另外从其示意曲线估值或据此拼造SD。
- 第3页2.2明确CAR阴性功能对照为 `PLJM1-EGFP` 慢病毒转导T细胞，第6页3.2说明后续实验采用MOI10。故这些对照的杀伤和细胞因子结果仅关联共享的MOI10工艺，`binder.binder_id`、`car.car_id`、`combination_id` 均空；不新增仅为对照外键服务的工艺。
- `evidence` 第67–78行每个效应细胞组与培养条件合并图6A–C三个24小时上清读出：IFN-γ进入 `manufacturing.ifn_gamma_release`，IL-2和TNF-α依图面板顺序进入 `manufacturing.cytokine_release`。同一组不同细胞因子不拆成独立实验。正文2.9及3.6的E:T 6:1与图6图注1:1冲突，共培养行的 `applicable_scenario` 并列保留；单培养不赋E:T。该源文歧义已记录于异常日志。

## 覆盖核查

| 实验、流程或合格实体及来源 | 最终状态 | 输出定位或缺口原因 |
|---|---|---|
| CD19-specific VHH；第2、3、10页 | 已覆盖 | `binder` 第1行 `name/target_antigen/humanization_level`；`evidence` 第19行 `binder.immunogenicity_ada_risk`；未报告序列不补造 |
| FMC63阳性对照；第3页2.2 | 已覆盖 | `binder` 第2行 `name/target_antigen`；来源未说明的链序列与人源化字段为空 |
| 共同骨架与CAR克隆；第3页2.2–2.3 | 部分覆盖 | `car` 第3行 `name/modules`；CD8α具体模块类型不明；PCR核酸引物、限制酶与克隆试剂没有当前实体字段目的地 |
| PBMC分离、激活、五MOI转导与培养；第2–4页2.1、2.6 | 已覆盖 | `manufacturing` 第4–8行 `selection_steps/activation_method/reagents/moi/transduction_transfection_conditions/culture_system/cytokine_combination`；`evidence` 第20–29行 `applicable_scenario` 保留离心参数 |
| HEK293T包装与PEI:DNA优化；第3、5页、图1 | 未存储 | 已查看1:1、2:1、3:1、4:1及染色/无PEI对照；2:1被选用。检测对象为病毒包装细胞，当前表无对应目的地，不误存为T细胞活率或转导效率 |
| HEK293T病毒滴定和整合qPCR；第3–4页2.5、第6页3.2 | 未存储 | 已核查稀释、培养、qPCR方法；病毒滴度相关结果注明“data not shown”，无可提取T细胞VCN；无匹配活动字段 |
| 两种CAR-T的五MOI优化；第6页图2A–B | 已覆盖 | `evidence` 第20–29行 `manufacturing.cell_viability/cd3_positive_ratio/car_positive_ratio`；图2A各组精确标签优先，不与图2B重复估算 |
| 最终CAR表达及染色对照；第7页图3A–D | 已覆盖 | `evidence` 第30、31行 `manufacturing.cd3_positive_ratio/car_positive_ratio`；未染色与未转导图用于判读背景，不虚构独立CAR实体 |
| 72小时增殖；第4页2.7、第7–8页、图4 | 已覆盖 | `evidence` 第32–39行 `car.expansion_capacity/applicable_scenario`；含单培养、3种靶细胞、无IL-2、CFSE条件、mitomycin C处理和匹配阴性对照 |
| 16小时杀伤；第4页2.8、第7–9页、图5 | 已覆盖 | `evidence` 第40–66行 `manufacturing.killing_activity/applicable_scenario`；3效应组×3靶细胞×3个实际E:T，共27行，n=3 |
| 24小时细胞因子释放；第4页2.9、第8、10页、图6 | 已覆盖，比例歧义保留 | `evidence` 第67–78行 `manufacturing.ifn_gamma_release/cytokine_release/applicable_scenario`；3效应组×4培养条件，每行3个读出，共36个图像范围；E:T冲突未消解 |

## 图像估算的可追溯依据

仅图6缺少明示浓度标签，进行柱顶均值的像素估算。来源为原PDF第10页内嵌图6，3815×1937像素；无网络图片替换。以下裁剪框为原图左上原点的 `(左, 上, 右, 下)`，区间坐标为对应裁剪图像的像素。所有轴均线性；图6A断轴分段独立校准，不跨断轴插值。

| 图与裁剪 | 两个可读刻度：像素y→pg/mL | 映射 |
|---|---|---|
| 图6A，(0,0,1900,920)，1900×920，低段 | 788→0；511→800 | `v=(788-y)×800/277` |
| 图6A，同上，高段 | 363→8000；86→14000 | `v=8000+(363-y)×6000/277` |
| 图6B，(1900,0,3815,920)，1915×920 | 788→0；40→2000 | `v=(788-y)×2000/748` |
| 图6C，(900,1000,2950,1937)，2050×937 | 829→0；82→800 | `v=(829-y)×800/747` |

横轴依组为CAR-Neg、VHH-CAR、scFv-CAR，每组依图例为Single culture、K562、Ramos、Raji。实心柱以顶缘上下各4像素包围边缘与轴刻度定位误差；有黑色边框的柱顶黑线约10–11像素厚，以外顶缘前4像素至后14像素涵盖该边框和定位误差。下表均是该柱顶区间，不取误差条端点。映射后低浓度向外取整至10 pg/mL，IFN-γ高轴段向外取整至100 pg/mL；范围仅表示读图精度。已在叠加标记图中逐柱复查。图注明确误差条为SD，但无明示数值，`error`留空，不从估算范围制造SD或均值。

下表每格格式为 `x；y区间→浓度范围`，单位均为pg/mL。三个读出依次对应 `manufacturing.ifn_gamma_release`、`manufacturing.cytokine_release[0].concentration`（IL-2）、`manufacturing.cytokine_release[1].concentration`（TNF-α），均在同一 `evidence` 行。

| evidence物理行 | 源组别与24小时培养条件 | 图6A IFN-γ | 图6B IL-2 | 图6C TNF-α |
|---|---|---|---|---|
| 67 | CAR-Neg，Single culture | 344；762–770→50–80 | 358；760–768→50–80 | 360；810–818→10–30 |
| 68 | CAR-Neg，K562 | 426；733–751→100–160 | 439；736–754→90–140 | 442；782–800→30–60 |
| 69 | CAR-Neg，Ramos | 509；727–745→120–180 | 522；739–757→80–140 | 524；781–799→30–60 |
| 70 | CAR-Neg，Raji | 590；728–746→120–180 | 604；740–758→80–130 | 606；786–804→20–50 |
| 71 | VHH-CAR，Single culture | 726；742–750→100–140 | 740；733–741→120–150 | 743；796–804→20–40 |
| 72 | VHH-CAR，K562 | 808；715–733→150–220 | 822；717–735→140–190 | 825；783–801→20–50 |
| 73 | VHH-CAR，Ramos | 890；295–313→9000–9500 | 905；288–306→1280–1340 | 907；374–392→460–490 |
| 74 | VHH-CAR，Raji | 972；258–276→9800–10300 | 987；275–293→1320–1380 | 989；349–367→490–520 |
| 75 | scFv-CAR，Single culture | 1108；756–764→60–100 | 1123；733–741→120–150 | 1125；795–803→20–40 |
| 76 | scFv-CAR，K562 | 1190；719–737→140–200 | 1205；716–734→140–200 | 1208；784–802→20–50 |
| 77 | scFv-CAR，Ramos | 1272；245–263→10100–10600 | 1287；251–269→1380–1440 | 1290；362–380→480–510 |
| 78 | scFv-CAR，Raji | 1354；200–218→11100–11600 | 1369；231–249→1440–1490 | 1372；299–317→540–570 |

## 校验、执行方式与交付

本次为单代理提取并由同一代理回查原文，未启用子代理或独立代理交叉提取。已完成方法、结果、图注和图1–6的覆盖复查及语义复查，核对组别、实验阶段、门控分母、量纲、来源位置和引用归属。通用背景、其他论文的临床结果以及对VHH低聚集/低免疫原性的泛化论述未作为本文实测结果。

最终文件已按活动YAML检查JSONL结构、类型、枚举、对象/数组形状、measurement数值形态、非空本地标签、外键存在及先后顺序、组合与证据归属、来源标识和百分比/非负数值约束；项目 `prepare_output` 已只读验证通过，未用其返回值覆盖本次来源数据。未输出注释字段 `evidence_level`、`experimental_conditions`、`corresponding_car_product`。仅使用报告过的条件组合，保留既定行序与列表顺序。

最终共78行：`binder` 2行、`car` 1行、`manufacturing` 5行、`abc_combination_db1` 10行、`evidence` 60行；本次异常2项。例外分别是CD8α模块类型不明，以及图6共培养E:T比例冲突；均保留可用记录。在线附件清单核查受DNS失败限制。UUID替换、可空字段补全与单位归一化由runner在发布阶段执行，当前未宣称这些发布步骤已经完成。临时图像、清单、脚本、草稿及检查记录均位于独立的 `scratch/`，只发布 `data.jsonl`、`reasoning.md`、`error_log.jsonl`。
