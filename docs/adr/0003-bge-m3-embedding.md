---
status: accepted
---

# 使用 BAAI/bge-m3 作为记忆系统 Embedding 模型

MathTutor 记忆系统正式选择云端 `BAAI/bge-m3` 作为 HMS 的 Embedding 模型。

配置约束：

```text
HMS Provider：openai-compatible
向量类型：dense vector
向量维度：1024
```

选择原因：

```text
支持中文和中英文混合语义检索。
适合错因、知识点、学习偏好和反思等记忆文本。
云端部署不要求 MathTutor 服务器本地加载模型。
相比 HMS 默认英文模型，更符合中文数学辅导场景。
```

上线前必须使用 MathTutor 自建测试集验证中文错因召回、同义表达召回、无关记忆误召回、延迟和费用。

同一个 HMS 向量索引必须保持模型和维度一致。不得在运行中静默切换到 M3E 或其他模型；以后更换 Embedding 模型时，必须重新生成全部记忆向量并重建索引。
