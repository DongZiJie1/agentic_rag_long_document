# agentic_rag_long_document
现有的 RAG 方案在处理 100k+ tokens 时往往死于“中间信息丢失（Lost in the Middle）”。本项目拒绝简单的 Top-K 向量堆砌，而是通过动态上下文压缩与多步推理分发，解决长文档在 RAG 流程中的信噪比坍塌问题。
