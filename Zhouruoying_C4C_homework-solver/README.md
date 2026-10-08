# C4C homework-solver —— 使用与设计说明

这是一个「**作业自动求解 + 排版**」技能：给一份 Markdown 作业，产出可提交的 PDF。

- 技能包：`Zhouruoying_C4C_homework-solver/`（源码）与 `Zhouruoying_C4C_homework-solver.skill`（打包）
- 本地模型：**Qwen3-8B**（`qwen3:8b`，本机 Ollama 0.34.4）
- 示例产物：`Zhouruoying_C4C_output.pdf`（13 题，7 页）

---

## 1. 核心设计：三层分工

```
作业.md → ①读入 → ②解析 → ③分类 → ④求解 → ⑤核验 → ⑥排版 → ⑦编译 → PDF
                              ▲
                    本地模型只在这一步出手（判域 / 兜底规范化 / 写一句思路）
```

| 层 | 由谁负责 | 为什么 |
|---|---|---|
| 理解与归类 | 本地大模型（Qwen3-8B） | 这是模型的强项 |
| 计算 | 确定性符号引擎（sympy） | 保证可复现、可核验 |
| 核验 | `verify.py`（**另一条算法路径**） | 不信任前两层，过了才放行 |

**为什么不让模型直接写答案**：模型算错时，页面上是一段看起来合理的错误推导，读者无法察觉。所以本技能把「计算」和「排版」从模型手里拿走。

## 2. 安装

```bash
python3 -m pip install sympy pyyaml        # 必需
python3 -m pip install numpy               # 可选（部分核验使用）

# 可选：本地模型
ollama pull qwen3:8b

# 可选：LaTeX 引擎（要出 PDF 才需要）：tectonic 或 xelatex 任一
```

自检：

```bash
cd Zhouruoying_C4C_homework-solver && python3 scripts/bootstrap.py
```

## 3. 使用

```bash
# 完整流程
python3 pipeline.py 作业.md output --compile --student 姓名 --course 课程名 --verbose

# 纯确定性模式（不接模型，先验证解析与分类）
python3 pipeline.py 作业.md output --no-llm

# 附加机器可读输出
python3 pipeline.py 作业.md output --json
```

**退出码**：`0` 成功 / `2` 有题目未过核验 / `3` 缺依赖或读入失败 / `4` 编译失败。

## 4. 目录

```
Zhouruoying_C4C_homework-solver/
├── SKILL.md              # 技能元信息与用法（包内入口说明）
├── README.md             # 本文件
├── pipeline.py           # 入口：七阶段编排
├── scripts/              # 13 个脚本（见 SKILL.md 表格）
├── references/           # 学科关键词表（新增学科加一个 yaml 即可）
└── examples/             # sample_homework.md
```

## 5. 核验层（关键）

`verify.py` 每条检查都**不复用求解器算法**：方程组→回代；特征值→`Av=λv` 残差；行列式→Berkowitz+LU 交叉；秩→SVD 计数；物理量→两条公式+量纲。
**核验不过 → 答案撤回，退出码 `2`。** 能进 PDF 的答案都过了独立核验。

## 6. 实测结果（本仓库交付的那次运行）

| 项 | 值 |
|---|---|
| 作业 | 《线性代数与大学物理 综合练习（第 6 次作业）》，13 题 |
| 已解 + 核验通过 | **11 题**，核验失败 **0** |
| 超范围（登记不答） | P08、P13 |
| 退出码 | `0` |
| PDF | `Zhouruoying_C4C_output.pdf`，103,093 字节，7 页 |
| 用时 | 16.25 秒 |

第二份样本 `examples/sample_homework.md`：12/13 解出并核验通过，退出码 `0`。

## 7. 复现

```bash
cd C4C
python3 Zhouruoying_C4C_homework-solver/pipeline.py \
    Zhouruoying_C4C_作业原件.md output \
    --compile --student Zhouruoying --course 线性代数与大学物理 --verbose
echo "rc=$?"    # 期望 0
```

## 8. 迁移

1. 换成你的作业 Markdown；
2. 先 `--no-llm` 看解析/分类；
3. 新题型反复出现时：在 `solvers_*.py` 加求解函数，**并在 `verify.py` 补一条独立核验**——只加求解不加核验不被接受。
