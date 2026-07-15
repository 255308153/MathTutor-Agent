# third_party：外部模型工程

## 定名

```text
模型名：SAFKT（唯一对外名称）
engine_name：safkt
源码实现类：class DKT（历史名，仅 import 用，禁止当模型名）
```

## 当前以哪份为准

| 项 | 路径 |
|----|------|
| 你下载的 GitHub 包 | `SAFKT/LDGEKT-explainability-sync-main/` |
| zip | `~/Downloads/LDGEKT-explainability-sync-main.zip` |
| 完整仓链接 | `third_party/LDGEKT-explainability-sync` → 上面包 |
| **SAFKT 可运行根** | `third_party/safkt` → `…/90_源码与原始工程/DGEKT原版-自注意力机制-master_副本` |

> 目录名里带「DGEKT原版-自注意力…」是源码文件夹历史命名；**模型叫 SAFKT。**

## SAFKT 包含

```text
KnowledgeTracing/model/Model.py
  ForgettingMechanism
  KnowledgeStateEncoder
  双图 + 自注意力 + 遗忘 + return_explanation   ← 这就是 SAFKT

KnowledgeTracing/explainability/
  paths / scoring / export / evaluation …
```

## 和旧副本

`/Users/lqc/Downloads/LDGEKT_副本` 仍在。  
**接入 MathTutor 时用 `SAFKT/` 这份，模型名写 SAFKT。**
