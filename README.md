# Zhouruoying_C4C 作业自动求解与排版 — homework-solver

C4C 挑战（`ch-20260717031447-k82c4m`）交付仓库。

## 这是什么

`homework-solver` 是一条**七阶段作业流水线**：把一份 Markdown 作业原件（含 LaTeX 数学）变成一份**带解答、带核验、可编译成 PDF** 的排版稿。

```
ingest → parse → classify → solve → verify → render → compile
```

- **solve**：先走确定性符号求解器（sympy/numpy）；解不出的，才让**本机 Ollama 上的 `qwen3:8b`** 做「规范化 + 讲解」（`explain_only`），模型输出**不直接当答案**，必须再回到确定性求解器复算。
- **verify**：每条答案由独立方法交叉验证（回代残差、特征对残差、秩的两种算法、行列式两种算法、双路径、量纲检查），`TOL=1e-8`。
- **render/compile**：生成 LaTeX 并调用本机 `tectonic`（XeTeX 内核）编译出 PDF。

**核心边界**：模型只负责「讲解与规范化」，**不负责下结论**。凡是模型规范化后仍无法确定性求解的题（本次为 P08 匀变速直线运动、P13 矩阵逆行列式证明），一律标记「超出模板范围」而**不编造答案**。

## 快速开始

```bash
# 依赖：Python 3.10+；sympy / numpy / pyyaml；本机 Ollama（qwen3:8b）；tectonic（或其它 XeTeX/LaTeX）
python3 Zhouruoying_C4C_homework-solver/scripts/bootstrap.py        # 环境自检

# 带本地模型 + 编译 PDF 的正式运行
python3 Zhouruoying_C4C_homework-solver/pipeline.py \
    Zhouruoying_C4C_作业原件.md output --compile \
    --student Zhouruoying --course 线性代数与大学物理 --verbose

# 无模型烟囱测试（CI 友好，不依赖 Ollama）
python3 Zhouruoying_C4C_homework-solver/pipeline.py \
    Zhouruoying_C4C_homework-solver/examples/sample_homework.md _smoke/run11 --no-llm --compile
```

退出码：`0` 全部核验通过 / `2` 有未通过 / `3` 缺依赖 / `4` 编译失败。

## 本次真实运行结果

| 项 | 值 |
|---|---|
| 作业原件 | `Zhouruoying_C4C_作业原件.md`（13 题：线性代数 6 / 大学物理 5 / 常微分方程 2） |
| 求解 | 11 题确定性求解 + 2 题判定超出范围（不编造） |
| 核验 | 11/11 通过，18 项检查中 16 项 PASS |
| 产出 | `Zhouruoying_C4C_output.pdf`（7 页，103,093 字节，`%PDF-1.5`） |
| 复现 | `output/logs/` 下 7 份阶段日志 + `包与盘一致性校验.txt` |

## 目录

| 路径 | 说明 |
|---|---|
| `Zhouruoying_C4C_homework-solver/` | 技能源码（`pipeline.py` + `scripts/` 13 个模块 + `references/` 3 份题型模板） |
| `Zhouruoying_C4C_homework-solver.skill` | 打包好的技能包（ZIP；20 文件） |
| `Zhouruoying_C4C_*.md` | 方案设计 / 作业原件 / 验证报告 / 教学说明 / AI日志 / 拿来说明 / 项目自评 / AAR（复盘） |
| `Zhouruoying_C4C_output.pdf` | 作业解答 PDF |
| `output/` | 解答 Markdown / LaTeX 源 / 7 份阶段日志 |
| `logs/` | 包与盘一致性校验 |

## 一句话结论

这条流水线把「模型讲解」和「确定性求解」分开：**模型可以帮忙，但不能替它下结论**——所以同一份作业复跑，解答与 PDF 都能复现。
