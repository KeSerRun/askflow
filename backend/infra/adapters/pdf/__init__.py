"""adapters.pdf —— MinerU 文档解析适配器。

当前实现：
- ``mineru_impl``：MinerU 本地 V1 API 客户端 + 分块（图片抽离 / md5 对齐可视化通用）；
- ``document_loader``：目录/文件加载管线 → 标准化 Document（供向量库入库）。

入口由调用方按需导入上述子模块；本包不导出轻量旧接口。
"""