# 第 32 章 Battle for Detroit — Source Outcomes → JSON 覆盖映射

## 目的

Fandom 攻略页面声明本章有 **61 个 outcomes**（Kara 27 / Connor 11 / Markus 23）。本章 JSON 定义了 **25 个 ending**。

**本表不是对 61 条 outcome 的逐项映射**——Fandom 的 61 含大量过场场景（见下节），逐项一一对应没有意义。本表做的是：把 source 归并后的**最终命运**逐项映射到 JSON 的 `ending` + 区分用 `state` 变量，并标注 JSON 节点实际能产出哪些 ending，以此说明压缩未丢失实质差异。

## 关键澄清：61 ≠ 61 个最终结局

Fandom 的 "outcomes" 计数把**中间场景结果**（标注 "leads to X" 的过场）一并计入，并非 61 个互斥的最终结局。例如 Kara 线的 "Line Moves Forward"、"Soldiers Are Distracted"、"Reach Recycling Machine" 都被计为 outcome，但它们是流程节点而非结局。真正互斥的**最终命运**远少于 61。

JSON 的设计是：**最终命运用 ending 表达；命运内部的细分组合用 state 变量保留。** 配合本次 runner 修复后的 `all_endings`（每个主角各输出一个 ending）和每节点 `state_after` 快照，所有有意义的最终差异均可还原。

---

## Connor（source 11 = CyberLife Tower 8 + Last Mission 3）

| Source 最终命运 | JSON ending | 额外区分用 state |
|---|---|---|
| 楼顶：Connor 放弃/离开 | `ending_connor_rooftop_left` / `ending_connor_gave_up` | `connor_rooftop_choice`, `connor_gave_up` |
| 楼顶：Connor 杀死 Hank | `ending_connor_killed_hank` | `connor_rooftop_choice=attack_hank` |
| 楼顶：Connor 被歼灭 | `ending_connor_rooftop_destroyed` | — |
| CyberLife 塔：唤醒万台仿生人（The Androids Woke Up） | `ending_androids_awakened` | `androids_awakened=true`, `hank_alive_ch32`, `connor_death_count` |
| CyberLife 塔：失败/仿生人沉睡（Remained Dormant） | `ending_connor_tower_failed` | `androids_awakened=false` |

**关于 "8 个 Tower outcomes"：** Both Connors Shoot / Connors Fight / Connors Draw / Hank Grabs Gun / 问狗名(Sumo) / 问儿子名 / Wrong Answer / Hank Kills Connor 等，都是**通往两个终态**（唤醒 or 沉睡）的过程分支。其中真正影响最终名单的是 Hank 与各 Connor 的生死，由 `hank_alive_ch32`、`connor_death_count` 和 ending 的 `deaths` 列表（Agent 54/47、Hank、Connor 60、Connor）承载，非独立结局。

---

## Markus（source 23 = Revolution 18 + Demonstration 5）

| Source 最终命运 | JSON ending | 额外区分用 state |
|---|---|---|
| 革命：进攻成功，革命胜利 | `ending_revolution_victory` | `revolution_attack_success=true`, `markus_store_choice` |
| 革命：Markus 死、革命失败（强攻战死/无人救心脏） | `ending_revolution_markus_died` | `revolution_markus_wounded`, `markus_heart_choice` |
| 商店：Connor 处决 Markus（Connor Executed Markus / Killed Each Other） | `ending_connor_executed_markus` | `ch30_connor_deviant`, `connor_gave_up` |
| 商店：引爆脏弹（Markus Died as Detroit Burns / Watched Detroit Burn） | `ending_detroit_burns` | `markus_store_choice=detonate`, `ch30_bomb_armed` |
| 商店：投降被杀（Markus Died Leaving Store） | `ending_store_surrender` | `markus_store_choice=surrender` |
| 商店：自尽（Markus Committed Suicide） | `ending_store_suicide` | `markus_store_choice=suicide` |
| North 主导且革命失败（North Was Shot / North & Connor Killed Each Other） | `ending_north_revolution_failed` | `ch30_north_alive`, `north_relationship` |
| 示威：唱歌/坚守，总统下令不开火（Androids Won Freedom） | `ending_demonstration_victory` | `demo_final_choice`, `public_opinion` |
| 示威：接受 Perkins 协议被出卖（Died After Betraying his People） | `ending_markus_accepted_deal` | `demo_perkins_choice=accept` |
| 示威：拒绝/被攻破，最后一搏战死（Markus Died with his People / Protecting） | `ending_barricade_last_stand` | `demo_final_choice`, `demo_perkins_choice=refuse` |

**关于 "胜利"的两条线：** 革命胜利 `ending_revolution_victory` 与 示威胜利 `ending_demonstration_victory` 通过 `ch31_markus_strategy`（violent/peaceful/north_attacks）区分，未合并。

---

## Kara（source 27 = Leaving Detroit 12 + Captured 15）

### Leaving Detroit（逃往加拿大）

| Source 最终命运 | JSON ending | 额外区分用 state |
|---|---|---|
| 巴士过境，全员（含 Luther）越境 | `ending_kara_border_crossed` | `luther_alive_ch32=true`（= Alice got to Canada with Luther） |
| 巴士过境，牺牲 Luther 制造混乱，Kara&Alice 越境 | `ending_kara_border_crossed` | `luther_alive_ch32=false`, `kara_saved_group` |
| 边境 Kara 自我牺牲，Alice 由 Rose 接走越境 | `ending_kara_sacrificed_self` | survivors=[Alice]（= Alice got to Canada with Rose） |
| 终点站/边境被士兵处决（Soldiers Executed Kara & Alice / + Luther） | `ending_kara_arrested` | `luther_alive_ch32`（区分是否含 Luther） |
| 河边（n015）：Kara & Alice 乘船/游泳生还 | `ending_kara_river_survived` | `kara_river_choice`（accelerate/dive 成功） |
| 河边（n015）：Alice 损毁关机、Kara 独自前行 | `ending_kara_left_without_alice` | dive 失败：Alice（YK500）冰水损毁，Kara 独活 |
| 河边（n015）：Kara & Alice 双双遇难/沉船 | `ending_kara_river_died` | accelerate 失败或 surrender |

> 河流节点（n015）实际产出三种结局：双生（river_survived）、Alice 死 Kara 活（left_without_alice，dive 失败）、双死（river_died）。源材料河边的第四种"Kara 死 Alice 活"不在河流节点产出，而由**边境节点 n014 的 `sacrifice_kara`** 承载（见上表 `ending_kara_sacrificed_self`：Kara 留下断后，Alice 越境）。

### Captured（回收中心）

| Source 最终命运 | JSON ending | 额外区分用 state |
|---|---|---|
| 逃出集中营（Escaped on Truck，含 Luther/Alice 组合） | `ending_kara_escaped_camp` | `luther_alive_ch32`, `kc_escape_choice`, `kara_saved_group` |
| 被 Markus 革命解救（Markus Liberates Androids） | `ending_kara_freed_revolution` | `markus_freed_camp=true` |
| 死于回收机/队列（Died in Recycling Machine / in the Lines） | `ending_kara_camp_died` | `kc_kara_wounded`, `kc_escape_choice` |

> 集中营节点（n016–n018）实际产出三种结局：逃出（escaped_camp）、被革命解救（freed_revolution）、死亡（camp_died）。源材料的冷门分支 "Kara Leaves Camp Without Alice"（Kara 爬卡车独自逃、抛下 Alice）**未单独建模**，被并入 `ending_kara_camp_died`（视为该次逃脱整体失败）。"Kara 独活失去 Alice" 这一最终命运由河流路径的 `ending_kara_left_without_alice` 承载，不在集中营重复建模。

**Luther/Rose/Ralph 细分：** "Alice got to Canada with Luther" vs "with Rose" 由 `luther_alive_ch32` + ending survivors 区分；Ralph 在集中营是否介入由 `ch13_ralph_defended` 携带；Rose 接走 Alice 对应 `ending_kara_sacrificed_self`（survivors=[Alice]）。

---

## 结论

- source 的 61 "outcomes" 含大量过场场景；归并后的最终命运对应 JSON 的 25 个 ending。映射是**归并关系**而非一一对应：多数细分组合由 `state` 变量保留，少数冷门分支（如 "Kara Leaves Camp Without Alice"）为有意识合并，已在上文逐条标注。
- Kara 河边/边境/集中营的生死组合、Connor 塔内 Hank 生死、Markus 革命 vs 示威胜利，均通过**独立 ending 或 state 变量**保留，可从结果文件还原。
- 经本轮修复，`ending_kara_left_without_alice` 已可达（河流 dive 失败触发）；runner 输出 `all_endings`（Connor/Markus/Kara 各一个 ending）+ 每节点 `state_after`，三线终局不再被压成单一 primary ending。

**已知有意识合并（非丢失，列明备查）：**
- 集中营 "Kara Leaves Camp Without Alice" 并入 `ending_kara_camp_died`。
- CyberLife 塔 8 个过场分支并入 `ending_androids_awakened` / `ending_connor_tower_failed` + `hank_alive_ch32` + `connor_death_count`。

判定：本章最终命运均可从 `ending` + `state` + `all_endings` 还原，上述合并为设计取舍而非缺陷。
