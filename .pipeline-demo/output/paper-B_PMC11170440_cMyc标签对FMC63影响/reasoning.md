# 来源与读取范围

论文：Lima 等，2024，*In silico and in vivo analysis reveal impact of c-Myc tag in FMC63 scFv-CD19 protein interface and CAR-T cell efficacy*。DOI：10.1016/j.csbj.2024.05.032；PMCID：PMC11170440。已读取用户提供的 13 页 PDF 正文、方法、图 1–6、表 1–4、图注及补充材料线索；参考文献和致谢不作为本研究的独立数据提取。

2026-10-14 按官方 PMC Cloud 资源目录取得版本 PMC11170440.1，核对题名及 DOI 一致后下载 XML、补充 DOCX 和主图 4–6。所有下载的 MD5 均与官方元数据一致。已读取补充方法、表 S1–S6、图 S1–S8 图注，并查看补充图 S4–S8 的实际图像。S1–S3 在 DOCX 中是 EMF/WMF，当前本地渲染器未能显示；相应图注、正文、表 1–3/表 S6 已读。这三幅图的 RMSD/IIP 没有活动 Schema 数值字段，未依赖未查看的曲线填值。图 S7 是距离曲线，S8 是结构快照，按补充文件的实际标签定位。

资源及检查记录（均存于 `scratch/`，不发布）：

- 官方版本目录：<https://pmc-oa-opendata.s3.amazonaws.com/?list-type=2&prefix=PMC11170440.&delimiter=/>
- 官方元数据：<https://pmc-oa-opendata.s3.amazonaws.com/PMC11170440.1/PMC11170440.1.json>
- XML：<https://pmc-oa-opendata.s3.amazonaws.com/PMC11170440.1/PMC11170440.1.xml>，确认补充附件为 `mmc1.docx`。
- 补充材料：<https://pmc-oa-opendata.s3.amazonaws.com/PMC11170440.1/mmc1.docx>，MD5 `be627e388424a8e55fd72ee7aea7a2a6`。
- 主图资源：同一已列出目录下的 `gr4.jpg`、`gr5.jpg`、`gr6.jpg`；下载并校验。PDF 内嵌图均为 2100 像素宽，比云端 776 像素宽 JPG 清晰，最终读图采用 PDF 内嵌原图。初次受限网络 DNS 失败后，官方资源已成功取得，不记作遗留缺失。

# 实体、归属与字段决策

一个 FMC63 Binder（binder 第 1 行）用于三个构型。双 c-Myc 标签没有改变来源描述的 VL/VH 结合域，不新建 Binder；N/C 端位置在 car 第 3/4 行 `modules.source_molecule` 和对应证据场景中明确区分。标签序列 `EQKLISEEDL-EQKLISEEDL` 保留源分隔符，长度 20 来自两个 10 aa 标签。CD8α 信号肽没有模块枚举目的地；未填成 hinge。来源未指明跨膜区来源分子，保持空值；未从常用 CAR 构型补齐。CDR 长度直接按表 S1 原序列计数；缺编号体系的六段 CDR 不强配 IMGT/Kabat，详见异常日志。

制造工艺按实际步骤复用：三种 CAR 共用 manufacturing 第 5 行；Mock 的 SB100X-only 处理有明确不同的 DNA 投料，单独为第 6 行。未按供者、产品或结果拆成多份相同工艺。健康供者并不明确对应自体/异体临床关系，`t_cell_source` 留空。激活发生在电转后 2 h，未倒填为激活后转导等待时间；Nalm-6 的 X-001 电转没有混入 CAR-T 工艺。TransAct 的 `1:200` 在原文和激活描述中保留，试剂数值表示其比值 0.005；IL-2 保持原单位 U/mL。

abc_combination_db1 第 7–9 行依次为无标签、N 端标签、C 端标签的真实组合，最远阶段均为研究级动物实验 `in_vivo`。单独 Mock 证据不伪造 Binder/CAR/组合。流式 CAR+ 门百分比存入 `manufacturing.car_positive_ratio`，不写 `transduction_efficiency`；Mock 的门内背景不解释为真实 CAR 插入。代表性流式图与供者汇总图保留各自来源，不假设不同面板是新增独立重复或可跨面板配对。

4 h 图 5B 的结果是百分比裂解，可以保存为 `killing_rate`。图 6A 的纵轴是活 GFP+ 靶细胞数，动物图是发光总通量/动物生存，因此不转换成杀伤率或 CAR-T 持久性。Kd/Kon/Koff/Tm、释放细胞因子等未报告的测量保持空值。`evidence_level`、`experimental_conditions` 等注释字段均未输出。

# 实验与流程覆盖清单

下列行号均为最终 `data.jsonl` 的一基物理行号；不引用会被 runner 改写的本地 ID。“部分覆盖”明确区分数值不可读、来源矛盾及缺少活动字段三种原因。

| 实验、过程或实体及来源位置 | 处理结果 | 输出位置或具体缺口 |
|---|---|---|
| FMC63 结合域及三种实际 CAR 构型；§2.5、图 S6A | 已覆盖 | binder 第 1 行；car 第 2–4 行；`linker`、`cdr_length`、`structure_template`、`modules`；完整 scFv/VH/VL 序列未报告；CDR 区域编号限制见异常 |
| scFv 单体建模与 700 ns 水相模拟；§§2.1、2.3.1、3.1、图 S1、表 S6 | 部分覆盖 | binder 第 1 行 `structure_template`；RMSD 无活动字段 |
| N 端 c-Myc-scFv 建模与 700 ns 水相模拟；同上 | 部分覆盖 | 与同一 binder 共用结合域；标签由 car 第 3 行 `modules` 表达；RMSD 无活动字段 |
| CD19 补环建模与 300 ns 模拟；§§2.1.2、2.3.1、3.1 | 未存储 | 研究对象为靶蛋白建模流程；无相应实体或模拟参数字段，不建制造工艺 |
| N 端标签与 CDR 的 IIP/位阻分析；§3.2、图 1–2、表 4 | 未存储 | IIP 和构象占比无活动字段；未伪装成 Kd、Tm 或聚集性 |
| 两种 scFv-CD19 对接；§§2.2、3.3、图 3、表 S1–S2 | 部分覆盖 | evidence，第 10–10 行，`binder.epitope`；结合面是模型与预设约束，不是新实测表位定位 |
| 无标签 scFv-CD19，1000 ns × 3 模拟及 MM-PBSA；§3.4、表 1–3、图 S2–S3 | 未存储 | RMSD、IIP、ΔG 无活动数值字段；未从 ΔG 推算 Kd |
| N 端标签 scFv-CD19，1000 ns × 3 模拟及 MM-PBSA；同上 | 未存储 | 同上；模型对已形成界面的稳定作用不等于真实 CAR 功能提高 |
| C 端 scFv-c-Myc，700 ns 模拟；§3.7、图 S5、表 4 | 未存储 | IIP 无活动字段；不创建改变结合域序列的虚构 Binder |
| C 端标签 CAR 膜模型与 400 ns 距离模拟；§3.8、图 S7–S8、补充方法 | 部分覆盖 | car 第 2–4 行 `modules` 中 CD8α hinge；45 aa 来自 Thr263–Asp307（含端点）；nm 端距变化不写入以 aa 为单位的 `car.binder_length` |
| RS4;11/Nalm-6 GFP+Luc+ 与 CD19lo 靶细胞制备；§2.6、图 S4A | 部分覆盖 | 靶细胞名称和实验用途保留在对应 evidence 的 `applicable_scenario`/`target_cell_line`；靶细胞 CRISPR 流程、CD19 MFI 无活动字段，不套入 T 细胞制造表 |
| 健康供者滤器回收、Ficoll 分离及 PBS 洗涤；§2.7 | 已覆盖 | manufacturing 第 5–6 行 `selection_steps`；80 mL PBS、25 min/400 g、慢加速/关闭制动、3 次洗涤及试剂来源 |
| 三种 CAR 的共用 pT3/SB100X 工艺；§§2.5、2.7 | 已覆盖 | manufacturing 第 5 行 `reagents`、`activation_method`、`culture_system`、`cytokine_combination`、`culture_duration`；evidence，第 11–14 行，`applicable_scenario`；电转、投料、激活时序、培养温度/气氛均保留 |
| SB100X-only Mock 制备；§2.7 | 已覆盖 | manufacturing 第 6 行；与 CAR 工艺区别是未加 CAR 质粒，非另造虚构 CAR；Mock 只链接制造实体 |
| 图 4A–B 的 CAR 检测与 MFI；§3.5 | 部分覆盖 | evidence，第 19–32 行，`manufacturing.car_positive_ratio`；只保存可分辨图点；遮挡及跨构型概述不分摊，MFI 无活动字段 |
| 图 4C–F 记忆、CD4/CD8 与 PD-1/LAG-3/TIM-3；§3.5 | 部分覆盖 | evidence，第 15–18 行，`manufacturing.tcm_ratio / tem_ratio / teff_ratio / exhaustion_phenotype`；第 8 天 Teff 不可分辨；扩增后 CD4/CD8 不冒充起始比例，Naive 不冒充 Tscm |
| 图 5A、图 S4B、图 S6D 的代表性流式图 | 已覆盖 | evidence，第 33–35 行，`manufacturing.car_positive_ratio`；evidence，第 82–84 行，`manufacturing.car_positive_ratio`；evidence，第 117–120 行，`manufacturing.car_positive_ratio`；图 S4B 以全图细胞为分母，未重新归一到 CD3+ 门 |
| Nalm-6，4 h Calcein 裂解；§2.8.1、图 5B 左 | 已覆盖 | evidence，第 36–77 行，`manufacturing.killing_activity`；3 组 × 7 个实际剂量点，保存结果、E:T、时间、方法、技术三重复及读板条件 |
| RS4;11，4 h Calcein 裂解；§2.8.1、图 5B 右 | 已覆盖 | evidence，第 36–77 行，`manufacturing.killing_activity`；3 组 × 7 点，按独立靶细胞条件分行 |
| Nalm-6 野生型异种移植，0.7/1.4 × 10^6 CAR+ 剂量；图 5C–G | 部分覆盖 | evidence，第 78–81 行，`applicable_scenario`；剂量/给药/对照/样本量保留，发光总量和动物生存率无活动字段 |
| Nalm-6 CD19lo，0.6 × 10^6 CAR+ 剂量；图 S4C–G | 部分覆盖 | evidence，第 85–86 行，`applicable_scenario`；两组各 n=5；生存组间 p=0.09，未改写成已证实优效；脾脏 GFP+ 肿瘤细胞比例无活动字段 |
| 三构型/两种检测试剂的 day 1/day 8 CAR 阳性率；图 S6B–C | 部分覆盖 | evidence，第 87–116 行，`manufacturing.car_positive_ratio`；保留 3 条源连线 × 实际检测试剂/构型组合 × 2 时点；重合端点不去重，MFI 无活动字段 |
| 图 S6E，8 天记忆表型 | 已覆盖 | evidence，第 121–124 行，`manufacturing.tcm_ratio / tem_ratio / teff_ratio`；源图说明为 CCR7/CD45RO，与图 4 的 CD62L/CD45RO 分开；保留 Mock 的源标签门控说明，不猜其阳性来源 |
| 1:1 长时裂解，3 名供者；§2.8.2、图 6A | 部分覆盖 | evidence，第 125–140 行，`manufacturing.killing_activity`；4 组在 48/96 h 的共同条件分行，基线记在场景；结果是活 GFP+ 靶细胞数，无对应字段，未换算杀伤率 |
| 名义 0.5:1 长时裂解；同上 | 部分覆盖 | evidence，第 125–140 行，`manufacturing.killing_activity`；保留 0.5:1 与 1.5 × 10^4:30 × 10^4 的原文冲突，结构化比例留空；未将其当成额外 0.05:1 组 |
| 三构型 Nalm-6 异种移植，1.5 × 10^6 CAR+；图 6B–D | 部分覆盖 | evidence，第 141–143 行，`applicable_scenario`；每组 n=5、day 15 肿瘤观察条件保留，动物生存和肿瘤通量无活动字段 |

# 图像读数与校准

所有估算均为 `image_estimated_range`，上下界只表达像素定位精度；不表示供者范围、SD/SEM 或置信区间，也未取中点。优先使用图 5A、S4B、S6D 的印刷数值。无标签数据点只取圆点/方块中心或柱顶，不把误差棒跨度当作结果；图 5B 的 ±SD 仅作为来源统计描述，未估造 error。

| 校准代号 | 源图、尺寸与裁剪 | 刻度及映射 |
|---|---|---|
| F4A | PDF 内嵌图 4，2100×1549；检查裁剪 (0,0,590,480)，坐标同原图 | 线性 y：0%=402，50%=87；p=(402-y)×50/315；标记中心 ±3 px，向外取整到 1%；不推断遮挡点数或供者对应 |
| F4C | 同图；裁剪 (1050,0,2100,490)，下表 y 坐标同原图 | 0%=402，100%=192；p=高度×100/210。day 1 两组的 Tcm 底界约 280，Tem 底界分别 304/300，Teff 底界约 332/331；day 8 Tem 顶界为 293/289。柱顶 192。差分高度误差 ±2–3 px；下表 F4C 像素数为等效端点 y=402-该层高度，原始分层边界在此给出 |
| F5B-Nalm-6 | PDF 内嵌图 5，2100×1853；裁剪 (980,0,2100,400) | 线性 y：0%=314，40%=85；p=(314-y)×40/229；中心 ±3 px，向外取整到 1% |
| F5B-RS4;11 | 同图、同裁剪 | 线性 y：0%=317，40%=100；p=(317-y)×40/217；中心 ±3 px，向外取整到 1% |
| F5B-X-Nalm-6 | 同裁剪的局部 x 坐标 | log2 x：1→148，2→209.5，4→271；r=2^((x-148)/61.5)。实际中间圆点 x=188,249,311,372,434，区间 ±3 px，向外到 0.01 E/T；首尾使用方法明示 0.78:1、50:1。未把点旁边的 1/2/4/8/16/32/64 刻度当成实际剂量 |
| F5B-X-RS4;11 | 同裁剪的局部 x 坐标 | log2 x：1→692，2→746.2，4→800.4；r=2^((x-692)/54.2)。中间圆点 x=727,782,836,890,944；其余同左图 |
| S6B-anti-FMC63 | DOCX `image6.png`，1413×883，透明背景合成白色，未缩放 | y：0%=493，60%=260；p=(493-y)×60/233；中心 ±3 px，基线处截到 0；源连线按各组 day 8 端点从上到下编号，不冒充原始供者编号 |
| S6B-anti-Myc | 同图 | y：0%=493，60%=272；p=(493-y)×60/221；其余同上，重合端点按三条源连线保留，不去重 |
| S6E | 同 DOCX 原图 | y：0%=825，80%=604；p=(825-y)×80/221；柱顶 ±3 px、向外到 1%；只读柱高，未猜误差类型 |

逐值核查索引（全部为 evidence 表物理行号；字段列省略共同前缀 `manufacturing.`）：

| 行号 | 字段 | 校准 | 读数像素区间 | 保存范围 |
|---|---|---|---|---|
| 15 | `tcm_ratio` | F4C | 312–316 | 40–43 % |
| 15 | `tem_ratio` | F4C | 375–381 | 10–13 % |
| 15 | `teff_ratio` | F4C | 371–377 | 11–15 % |
| 16 | `tcm_ratio` | F4C | 312–316 | 40–43 % |
| 16 | `tem_ratio` | F4C | 379–385 | 8–11 % |
| 16 | `teff_ratio` | F4C | 368–374 | 13–17 % |
| 17 | `tcm_ratio` | F4C | 299–303 | 47–50 % |
| 17 | `tem_ratio` | F4C | 291–295 | 50–53 % |
| 18 | `tcm_ratio` | F4C | 303–307 | 45–48 % |
| 18 | `tem_ratio` | F4C | 287–291 | 52–55 % |
| 19 | `car_positive_ratio` | F4A | 380–386 | 2–4 % |
| 20 | `car_positive_ratio` | F4A | 340–346 | 8–10 % |
| 21 | `car_positive_ratio` | F4A | 376–382 | 3–5 % |
| 22 | `car_positive_ratio` | F4A | 390–396 | 0–2 % |
| 23 | `car_positive_ratio` | F4A | 340–346 | 8–10 % |
| 24 | `car_positive_ratio` | F4A | 256–262 | 22–24 % |
| 25 | `car_positive_ratio` | F4A | 223–229 | 27–29 % |
| 26 | `car_positive_ratio` | F4A | 232–238 | 26–27 % |
| 27 | `car_positive_ratio` | F4A | 254–260 | 22–24 % |
| 28 | `car_positive_ratio` | F4A | 260–266 | 21–23 % |
| 29 | `car_positive_ratio` | F4A | 158–164 | 37–39 % |
| 30 | `car_positive_ratio` | F4A | 175–181 | 35–37 % |
| 31 | `car_positive_ratio` | F4A | 245–251 | 23–25 % |
| 32 | `car_positive_ratio` | F4A | 271–277 | 19–21 % |
| 36 | `killing_activity.killing_rate` | F5B-Nalm-6 | 298–304 | 1–3 % |
| 37 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=185–191 | 1.51–1.63 E/T |
| 37 | `killing_activity.killing_rate` | F5B-Nalm-6 | 285–291 | 4–6 % |
| 38 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=246–252 | 3.01–3.23 E/T |
| 38 | `killing_activity.killing_rate` | F5B-Nalm-6 | 291–297 | 2–5 % |
| 39 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=308–314 | 6.06–6.5 E/T |
| 39 | `killing_activity.killing_rate` | F5B-Nalm-6 | 290–296 | 3–5 % |
| 40 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=369–375 | 12.07–12.92 E/T |
| 40 | `killing_activity.killing_rate` | F5B-Nalm-6 | 289–295 | 3–5 % |
| 41 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=431–437 | 24.27–25.98 E/T |
| 41 | `killing_activity.killing_rate` | F5B-Nalm-6 | 307–313 | 0–2 % |
| 42 | `killing_activity.killing_rate` | F5B-Nalm-6 | 279–285 | 5–7 % |
| 43 | `killing_activity.killing_rate` | F5B-Nalm-6 | 271–277 | 6–8 % |
| 44 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=185–191 | 1.51–1.63 E/T |
| 44 | `killing_activity.killing_rate` | F5B-Nalm-6 | 254–260 | 9–11 % |
| 45 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=246–252 | 3.01–3.23 E/T |
| 45 | `killing_activity.killing_rate` | F5B-Nalm-6 | 227–233 | 14–16 % |
| 46 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=308–314 | 6.06–6.5 E/T |
| 46 | `killing_activity.killing_rate` | F5B-Nalm-6 | 204–210 | 18–20 % |
| 47 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=369–375 | 12.07–12.92 E/T |
| 47 | `killing_activity.killing_rate` | F5B-Nalm-6 | 185–191 | 21–23 % |
| 48 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=431–437 | 24.27–25.98 E/T |
| 48 | `killing_activity.killing_rate` | F5B-Nalm-6 | 170–176 | 24–26 % |
| 49 | `killing_activity.killing_rate` | F5B-Nalm-6 | 127–133 | 31–33 % |
| 50 | `killing_activity.killing_rate` | F5B-Nalm-6 | 275–281 | 5–7 % |
| 51 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=185–191 | 1.51–1.63 E/T |
| 51 | `killing_activity.killing_rate` | F5B-Nalm-6 | 254–260 | 9–11 % |
| 52 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=246–252 | 3.01–3.23 E/T |
| 52 | `killing_activity.killing_rate` | F5B-Nalm-6 | 241–247 | 11–13 % |
| 53 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=308–314 | 6.06–6.5 E/T |
| 53 | `killing_activity.killing_rate` | F5B-Nalm-6 | 181–187 | 22–24 % |
| 54 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=369–375 | 12.07–12.92 E/T |
| 54 | `killing_activity.killing_rate` | F5B-Nalm-6 | 186–192 | 21–23 % |
| 55 | `killing_activity.effector_target_ratio` | F5B-X-Nalm-6 | x=431–437 | 24.27–25.98 E/T |
| 55 | `killing_activity.killing_rate` | F5B-Nalm-6 | 177–183 | 22–24 % |
| 56 | `killing_activity.killing_rate` | F5B-Nalm-6 | 165–171 | 24–27 % |
| 57 | `killing_activity.killing_rate` | F5B-RS4;11 | 227–233 | 15–17 % |
| 58 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=724–730 | 1.5–1.63 E/T |
| 58 | `killing_activity.killing_rate` | F5B-RS4;11 | 231–237 | 14–16 % |
| 59 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=779–785 | 3.04–3.29 E/T |
| 59 | `killing_activity.killing_rate` | F5B-RS4;11 | 231–237 | 14–16 % |
| 60 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=833–839 | 6.06–6.56 E/T |
| 60 | `killing_activity.killing_rate` | F5B-RS4;11 | 240–246 | 13–15 % |
| 61 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=887–893 | 12.1–13.08 E/T |
| 61 | `killing_activity.killing_rate` | F5B-RS4;11 | 246–252 | 11–14 % |
| 62 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=941–947 | 24.15–26.08 E/T |
| 62 | `killing_activity.killing_rate` | F5B-RS4;11 | 244–250 | 12–14 % |
| 63 | `killing_activity.killing_rate` | F5B-RS4;11 | 238–244 | 13–15 % |
| 64 | `killing_activity.killing_rate` | F5B-RS4;11 | 240–246 | 13–15 % |
| 65 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=724–730 | 1.5–1.63 E/T |
| 65 | `killing_activity.killing_rate` | F5B-RS4;11 | 168–174 | 26–28 % |
| 66 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=779–785 | 3.04–3.29 E/T |
| 66 | `killing_activity.killing_rate` | F5B-RS4;11 | 147–153 | 30–32 % |
| 67 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=833–839 | 6.06–6.56 E/T |
| 67 | `killing_activity.killing_rate` | F5B-RS4;11 | 152–158 | 29–31 % |
| 68 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=887–893 | 12.1–13.08 E/T |
| 68 | `killing_activity.killing_rate` | F5B-RS4;11 | 146–152 | 30–32 % |
| 69 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=941–947 | 24.15–26.08 E/T |
| 69 | `killing_activity.killing_rate` | F5B-RS4;11 | 164–170 | 27–29 % |
| 70 | `killing_activity.killing_rate` | F5B-RS4;11 | 160–166 | 27–29 % |
| 71 | `killing_activity.killing_rate` | F5B-RS4;11 | 199–205 | 20–22 % |
| 72 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=724–730 | 1.5–1.63 E/T |
| 72 | `killing_activity.killing_rate` | F5B-RS4;11 | 188–194 | 22–24 % |
| 73 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=779–785 | 3.04–3.29 E/T |
| 73 | `killing_activity.killing_rate` | F5B-RS4;11 | 187–193 | 22–24 % |
| 74 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=833–839 | 6.06–6.56 E/T |
| 74 | `killing_activity.killing_rate` | F5B-RS4;11 | 153–159 | 29–31 % |
| 75 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=887–893 | 12.1–13.08 E/T |
| 75 | `killing_activity.killing_rate` | F5B-RS4;11 | 160–166 | 27–29 % |
| 76 | `killing_activity.effector_target_ratio` | F5B-X-RS4;11 | x=941–947 | 24.15–26.08 E/T |
| 76 | `killing_activity.killing_rate` | F5B-RS4;11 | 135–141 | 32–34 % |
| 77 | `killing_activity.killing_rate` | F5B-RS4;11 | 133–139 | 32–34 % |
| 87 | `car_positive_ratio` | S6B-anti-FMC63 | 462–468 | 6–8 % |
| 88 | `car_positive_ratio` | S6B-anti-FMC63 | 307–313 | 46–48 % |
| 89 | `car_positive_ratio` | S6B-anti-FMC63 | 486–492 | 0–2 % |
| 90 | `car_positive_ratio` | S6B-anti-FMC63 | 384–390 | 26–29 % |
| 91 | `car_positive_ratio` | S6B-anti-FMC63 | 490–493 | 0–1 % |
| 92 | `car_positive_ratio` | S6B-anti-FMC63 | 443–449 | 11–13 % |
| 93 | `car_positive_ratio` | S6B-anti-FMC63 | 404–410 | 21–23 % |
| 94 | `car_positive_ratio` | S6B-anti-FMC63 | 307–313 | 46–48 % |
| 95 | `car_positive_ratio` | S6B-anti-FMC63 | 478–484 | 2–4 % |
| 96 | `car_positive_ratio` | S6B-anti-FMC63 | 316–322 | 44–46 % |
| 97 | `car_positive_ratio` | S6B-anti-FMC63 | 404–410 | 21–23 % |
| 98 | `car_positive_ratio` | S6B-anti-FMC63 | 342–348 | 37–39 % |
| 99 | `car_positive_ratio` | S6B-anti-FMC63 | 444–450 | 11–13 % |
| 100 | `car_positive_ratio` | S6B-anti-FMC63 | 299–305 | 48–50 % |
| 101 | `car_positive_ratio` | S6B-anti-FMC63 | 469–475 | 4–7 % |
| 102 | `car_positive_ratio` | S6B-anti-FMC63 | 359–365 | 32–35 % |
| 103 | `car_positive_ratio` | S6B-anti-FMC63 | 486–492 | 0–2 % |
| 104 | `car_positive_ratio` | S6B-anti-FMC63 | 423–429 | 16–19 % |
| 105 | `car_positive_ratio` | S6B-anti-Myc | 441–447 | 12–15 % |
| 106 | `car_positive_ratio` | S6B-anti-Myc | 356–362 | 35–38 % |
| 107 | `car_positive_ratio` | S6B-anti-Myc | 454–460 | 8–11 % |
| 108 | `car_positive_ratio` | S6B-anti-Myc | 356–362 | 35–38 % |
| 109 | `car_positive_ratio` | S6B-anti-Myc | 447–453 | 10–13 % |
| 110 | `car_positive_ratio` | S6B-anti-Myc | 377–383 | 29–32 % |
| 111 | `car_positive_ratio` | S6B-anti-Myc | 450–456 | 10–12 % |
| 112 | `car_positive_ratio` | S6B-anti-Myc | 333–339 | 41–44 % |
| 113 | `car_positive_ratio` | S6B-anti-Myc | 472–478 | 4–6 % |
| 114 | `car_positive_ratio` | S6B-anti-Myc | 385–391 | 27–30 % |
| 115 | `car_positive_ratio` | S6B-anti-Myc | 477–483 | 2–5 % |
| 116 | `car_positive_ratio` | S6B-anti-Myc | 437–443 | 13–16 % |
| 121 | `tcm_ratio` | S6E | 714–720 | 38–41 % |
| 121 | `tem_ratio` | S6E | 754–760 | 23–26 % |
| 121 | `teff_ratio` | S6E | 781–787 | 13–16 % |
| 122 | `tcm_ratio` | S6E | 722–728 | 35–38 % |
| 122 | `tem_ratio` | S6E | 672–678 | 53–56 % |
| 122 | `teff_ratio` | S6E | 805–811 | 5–8 % |
| 123 | `tcm_ratio` | S6E | 716–722 | 37–40 % |
| 123 | `tem_ratio` | S6E | 680–686 | 50–53 % |
| 123 | `teff_ratio` | S6E | 815–821 | 1–4 % |
| 124 | `tcm_ratio` | S6E | 726–732 | 33–36 % |
| 124 | `tem_ratio` | S6E | 667–673 | 55–58 % |
| 124 | `teff_ratio` | S6E | 807–813 | 4–7 % |

# 异常与完成检查

本次异常共 4 项，均有简体中文 `message`：CDR 必需编号体系缺失；图 4C 第 8 天 Teff 细层不能可靠分辨；图 4A 部分供者点遮挡/重复数不明；长时裂解名义 0.5:1 与原细胞数相矛盾。仅在最小受影响范围留空或保留可辨值，未删除其余可用数据。普通未报告字段、无活动字段的指标和背景引用不登记为异常。

已由同一提取者返回方法、结果、图注、表格核对覆盖，并复核结合域/标签、工艺阶段、外键、单位、分母、时间、对照与结果含义。单代理完成；按本次要求没有启动子代理，也没有独立双代理交叉检查。补充 S1–S3 的视觉限制如上。

本地已调用项目 `prepare_output` 在内存中检查 JSONL、活动字段、类型、枚举、嵌套结构、measurement 结构与引用；未用其返回值覆盖本地标签和原单位。另行检查实体在前、引用目标一致、组合与三外键相符、百分比/非负数边界及所有估算与索引一致。该检查不等于自动证明所有科学解释正确。最终 UUID 重写、缺省字段补全和正式单位归一化由 runner 后续执行，当前不能声称已发布或已完成该步骤。

仅 `data.jsonl`、`reasoning.md`、`error_log.jsonl` 是最终产物；下载、脚本和检查材料均在私有 `scratch/` 中。

写入行数：`binder` 1；`car` 3；`manufacturing` 2；`abc_combination_db1` 3；`evidence` 134；总计 143 行。
