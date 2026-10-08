---
name: homework-solver
description: 把一份真实作业（Markdown）自动求解并排版成可提交的 PDF。本地大模型（Ollama + qwen3:8b）只负责「判域 / 规范化兜底 / 写解题要点」，真正的计算交给确定性符号引擎（sympy），再由一条独立路径（回代 / 换算法 / 量纲）复核——核验不过的答案会被撤回。适合「线性代数 + 大学物理」域内作业，域外题型登记为「超出模板范围」而不编造答案。
---

# homework-solver —— 作业自动求解与排版流水线

> 一句话：**模型负责理解，代码负责计算，核验负责兜底。**

## 1. 它在做什么

输入一份作业（Markdown，每题一段），输出一份带解题过程与答案的 PDF：

```
作业.md → ①读入 → ②解析 → ③分类 → ④求解 → ⑤核验 → ⑥排版 → ⑦编译 → output.pdf
                              ▲                                   
                     本地模型只在这一步出手
                     （判域 / 兜底规范化 / 写一句思路）
```

**为什么不让模型直接写答案**：模型算错时，页面上是一段看起来很合理的错误推导，读者无法察觉。本技能把「计算」与「排版」从模型手里拿走，只留下模型真正擅长的「理解与归类」。

## 2. 安装与依赖

```bash
# 必需：Python 3.10+ 与两个库
python3 -m pip install sympy pyyaml

# 可选：numpy（部分核验会用到）
python3 -m pip install numpy

# 可选：本地模型（不装则自动退化为纯规则模式，仍可跑）
#   需要本机有 ollama 服务，并已拉取 qwen3:8b
ollama pull qwen3:8b

# 可选：LaTeX 引擎（要生成 PDF 时必须，任一即可）
#   tectonic（单文件版）或 xelatex
```

自检依赖：

```bash
python3 scripts/bootstrap.py
```

## 3. 使用

```bash
# 完整流程（接本地模型 + 编译 PDF）
python3 pipeline.py 我的作业.md output \
    --compile --student 姓名 --course 课程名 --verbose

# 不依赖模型，只用确定性规则（快，适合先验证解析是否正确）
python3 pipeline.py 我的作业.md output --no-llm

# 额外产出机器可读结果
python3 pipeline.py 我的作业.md output --json
```

**退出码**（可直接用于调度判断）：

| 码 | 含义 |
|---|---|
| `0` | 全部成功 |
| `2` | 有题目未通过核验（答案已撤回） |
| `3` | 环境依赖缺失，或读入/解析失败 |
| `4` | LaTeX 编译失败 |

## 4. 目录结构

```
Zhouruoying_C4C_homework-solver/
├── SKILL.md              # 本文件
├── README.md             # 更详细的使用与设计说明
├── pipeline.py           # 入口：七阶段编排
├── scripts/
│   ├── ingest.py         # ① 读入 + 归一化 + sha256
│   ├── parse_problems.py # ② 切题（P01…Pn）
│   ├── classify.py       # ③ 规则优先分类（读 references/*.yaml）
│   ├── llm_adapter.py    # ③ 本地模型适配（Ollama HTTP，超时/降级）
│   ├── solve.py          # ④ 求解编排 + 讲解
│   ├── solvers_algebra.py / solvers_ode.py / solvers_physics.py
│   ├── verify.py         # ⑤ 独立核验（另一条算法路径）
│   ├── render_latex.py   # ⑥ 生成 .tex（中文 XeLaTeX 模板）
│   ├── compile_pdf.py    # ⑦ 调引擎编译
│   ├── mathparse.py      # 数值/符号解析工具
│   └── bootstrap.py      # 依赖自检
├── references/           # 学科关键词表（新增学科只需加一个 yaml，不改代码）
│   ├── linear_algebra.yaml
│   ├── ode.yaml
│   └── physics.yaml
└── examples/
    └── sample_homework.md
```

## 5. 核验层（本技能最关键的部分）

`verify.py` 的每条检查都**故意不复用求解器的算法**：

| 题目类型 | 求解用的方法 | 核验用的**另一条路** |
|---|---|---|
| 线性方程组 | 直接求解 | **回代**原方程 |
| 特征值 | 特征多项式 | **`Av = λv` 残差** |
| 行列式 | 展开 | **Berkowitz + LU 交叉** |
| 矩阵的秩 | 行变换 | **SVD 奇异值计数** |
| 物理量 | 主公式 | **第二条公式 + 量纲检查** |

**核验不通过 → 答案标记撤回，流水线退出码 `2`。** 换句话说：能进 PDF 的答案，都过了独立核验。

## 6. 行为约定

- **不编造答案**：无法确定性求解的题登记为「超出模板范围」，页面留空，同时在日志里保留模型原始输出片段；
- **日志落盘**：全过程写 `output/logs/{01…07}_*.json`，模型调用记 `{prompt_sha256, prompt_chars, latency_s, ok, raw_excerpt}`；
- **离线可跑**：模型走本机 Ollama，无外网请求，零 API 费用。

## 7. 迁移到新作业

1. 换输入（作业写成 Markdown）；
2. 先跑 `--no-llm` 检查解析与分类；域外题会被标「超范围」；
3. 题型反复出现时，在 `solvers_*.py` 加求解函数，**并在 `verify.py` 补一条独立核验路径**——只加求解不加核验是不被接受的。
