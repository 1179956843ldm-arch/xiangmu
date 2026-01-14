# Enterprise Knowledge Base Assistant

## 项目简介
Enterprise Knowledge Base Assistant是一个企业知识库管理系统，旨在帮助企业高效管理和利用内部知识资源，提升组织协作效率和知识共享能力。
一个面向企业的 音频优先（Audio-first）RAG 知识助手，支持从音频上传到语义检索与可溯源问答的完整闭环。
## 项目结构
```
enterprise-kb-assistant/
├── .venv/                         # Python 虚拟环境
├── app/                           # 应用主目录
│   ├── audio/                     # 音频相关核心逻辑
│   │   ├── asr.py                 # 语音识别（ASR）
│   │   ├── audio_db.py            # 音频文档数据库访问
│   │   ├── audio_job_db.py        # 音频任务（job）数据库
│   │   ├── audio_loader.py        # 音频加载与预处理
│   │   ├── audio_tool.py          # 音频工具函数（裁剪、格式等）
│   │   ├── celery_app.py          # Celery 应用实例
│   │   ├── pipeline.py            # 音频处理流水线
│   │   ├── retrieve_audio.py      # 音频检索（RAG 召回）
│   │   └── segmenter.py           # 音频切分（segment）
│   │
│   ├── db/                        # 关系型数据库 & 缓存
│   │   ├── auth_db.py             # 用户认证数据
│   │   ├── kb_db.py               # 知识库数据
│   │   ├── leave_db.py            # 请假/业务示例数据
│   │   ├── mysql.py               # MySQL 连接与基础封装
│   │   ├── rbac_db.py             # RBAC 权限数据
│   │   └── redis_session.py       # Redis Session
│   │
│   ├── es/                        # Elasticsearch 相关
│   │   ├── es.py                  # ES 客户端与索引定义
│   │   └── es_audio_admin.py      # 音频 ES 管理（写入/删除/更新）
│   │
│   ├── ingestion/                 # 数据导入（预留/扩展）
│   │
│   ├── model/                     # Pydantic / 领域模型
│   │   ├── audio_admin_model.py
│   │   ├── audio_model.py
│   │   ├── auth_model.py
│   │   ├── kb_model.py
│   │   └── rbac_model.py
│   │
│   ├── prompts/                   # LLM Prompt 模板
│   │
│   ├── rag/                       # RAG 核心实现
│   │   ├── audio_hybrid.py        # 音频混合检索（ES + 向量）
│   │   ├── chroma.py              # Chroma 向量库封装
│   │   ├── chroma_admin_audio.py  # 音频向量管理
│   │   ├── chroma_admin_kb.py     # 知识库向量管理
│   │   ├── qa_graph.py            # QA 流程 / Graph
│   │   ├── torch_reranker.py      # 重排序模型
│   │   └── vectorstore.py         # 向量存储抽象
│   │
│   ├── scripts/                   # 脚本工具
│   │
│   ├── service/                   # 业务服务层
│   │
│   ├── tasks/                     # 异步任务（Celery）
│   │   └── audio_tasks.py         # 音频处理任务
│   │
│   ├── tools/                     # 通用工具函数
│   │
│   ├── web/                       # Web API（FastAPI）
│   │   ├── audio_admin_api.py     # 音频管理接口
│   │   ├── audio_api.py           # 音频问答 / 检索接口
│   │   ├── auth_api.py            # 认证接口
│   │   ├── kb_api.py              # 知识库接口
│   │   └── rbac_api.py            # 权限管理接口
│   │
│   └── workflows/                 # 应用编排 / 依赖注入
│       ├── data/
│       ├── leave/
│       ├── config.py              # 全局配置
│       ├── deps.py                # FastAPI 依赖
│       ├── main.py                # 应用入口
│       └── router_graph.py        # 路由/流程图
│
├── constants/
│   └── rbac_codes.py              # 权限码常量
│
├── data/                          # 运行期数据
│   ├── chroma/                    # Chroma 向量数据
│   ├── docs/                      # 原始文档 / 音频文件
│   └── tests/                     # 测试数据
│
├── tests/                         # 单元 / 集成测试
├── README.md                      # 项目说明
└── requirements.txt               # Python 依赖

```

## 主要功能
- 文档管理：支持上传、存储、分类和检索各种格式的文档

- 智能搜索：基于向量数据库的语义搜索功能

- 知识问答：基于企业知识库的智能问答系统

- 用户权限管理：支持不同角色的权限控制

- 音频文档管理

-支持音频文件上传、存储与元数据管理

-音频自动切分（segment）与时间戳标注

-支持音频可见性控制（public / internal）

-音频内容解析（ASR）

-自动语音识别（ASR），将音频转为可检索文本

-ASR 结果与音频片段一一对应，支持精确时间定位

-混合检索（Hybrid RAG）

-Elasticsearch 关键词检索（冷数据、可解释）

-向量数据库（Chroma）语义检索（召回）

-关键词 + 向量混合召回，提升命中率

-支持基于权限的检索过滤（visibility）

-智能问答（Audio RAG QA）

-基于音频内容的问答（RAG）

-支持多段音频证据拼接回答

-返回可定位的音频片段引用（clip URL）

-重排序与答案生成

-使用重排序模型（Torch Reranker）提升相关性

## 快速开始

### 环境要求
- Python 3.8+
- pip 20.0+

### 安装步骤
1. 克隆项目
```bash
git clone https://github.com/yourusername/enterprise-kb-assistant.git
cd enterprise-kb-assistant
```

2. 创建虚拟环境
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

3. 安装依赖
```bash
pip install -r requirements.txt
```

4. 启动应用
```bash
python app/main.py
```

## 文档管理
项目的`data/docs`目录用于存储企业文档，目前包含以下示例文档：
- 制度示例1：员工年假与请假管理
- 制度示例2：公司设备使用与管理办法

您可以将自己的文档添加到该目录，系统将自动索引并支持搜索。

## 贡献指南
1. Fork 项目
2. 创建您的特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交您的更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 打开Pull Request

## 许可证
[MIT](LICENSE)

## 联系方式
如有任何问题或建议，请联系：
- 项目维护者：[Your Name]
- 邮箱：[your.email@example.com]
- 项目地址：[https://github.com/yourusername/enterprise-kb-assistant](https://github.com/yourusername/enterprise-kb-assistant)

### 冷路径（Cold Path）

冷路径用于**准备和维护 RAG 所需的数据与索引**，不直接参与用户实时问答，
对延迟不敏感，通常发生在音频上传、解析或后台管理阶段。

典型操作包括：

- 创建和初始化 Elasticsearch 索引
- 将音频转写后的 segment 批量写入 ES
- 删除音频对应的检索数据
- 更新音频的可见性（visibility）
- 索引重建与维护

相关代码示例：
- `ensure_audio_index`
- `upsert_audio_segments`
- `delete_by_audio_id`
- `update_visibility_by_audio_id`

冷路径的目标是：**让热路径在查询时只做最少的工作**。


## 热路径（Hot Path）

热路径是**用户实时问答的核心执行链路**，从请求进入到返回答案，
**对延迟高度敏感**，任何阻塞都会直接影响用户体验。

热路径只做三件事：**校验权限 → 检索相关内容 → 调用 LLM 生成回答**。

### 典型入口

- `POST /audio/ask`
- `POST /audio/ask/stream`
- `GET  /audio/query`

---

### 执行流程（按先后顺序）

1. **请求校验**
   - 校验用户身份（JWT / session）
   - 校验问题参数是否合法
   - 计算用户可访问的 `visibility` 集合（保证包含 `public`）

2. **检索阶段（RAG Retrieval）**
   - 使用关键词在 Elasticsearch 中检索音频切分文本
   - 仅检索用户允许访问的 `visibility`
   - 按相关度返回 Top-K audio segments

3. **上下文构建**
   - 将命中的音频片段拼接为 LLM 上下文
   - 为每个片段生成可播放的 clip URL
   - 构造标准化的 LLM messages（system / user）

4. **LLM 推理**
   - 同步模式：一次性返回完整回答
   - 流式模式：通过 `llm.stream()` 持续向客户端推送 token

5. **响应输出**
   - 普通接口：返回完整 answer + citations
   - 流式接口：通过 SSE 实时输出模型生成内容

---

### 热路径设计原则

- ❌ 不做索引创建、数据写入、批量更新
- ❌ 不做长时间 IO 或后台任务
- ✅ 所有依赖数据必须已在冷路径中准备完成
- ✅ 每一步都可快速失败并返回明确错误

---

### 相关核心代码

- 权限与可见性计算  
  - `_compute_allowed_visibilities`
  - `_get_allowed_and_check`

- 检索  
  - `keyword_search`

- LLM 调用  
  - `_openai_chat_complete`
  - `_openai_stream`

热路径的目标是：  
**在最短时间内，用最少的数据，生成对用户最有价值的答案。**



一、音频上传 / 入库（写路径，冷但重）
POST /audio/ingest
   │
   ├─ 鉴权：get_current_user
   ├─ 权限校验：_require_manage_docs
   │
   ├─ 参数规范化
   │     ├─ _normalize_visibility
   │     └─ 生成 audio_id / job_id
   │
   ├─ 冲突校验
   │     ├─ is_audio_running
   │     └─ audio_id 是否存在 + overwrite
   │
   ├─ 文件落盘（AUDIO_DIR）
   │
   ├─ 写 audio_documents（status=queued）
   │
   ├─ 写 audio_jobs
   │
   ├─ 投递 Celery audio_ingest_task
   │
   └─ 返回 job_id / status_url

二、音频作业管理（管理路径）
GET  /audio/jobs/{job_id}
   │
   ├─ 鉴权
   ├─ _require_manage_docs
   ├─ audio_job_db.get_job
   └─ 返回作业状态

POST /audio/jobs/{job_id}/cancel
   │
   ├─ 鉴权
   ├─ _require_manage_docs
   ├─ request_cancel(job_id)
   └─ 返回 cancel_requested=true


三、音频搜索（query / search，读路径 · 热）


GET /audio/query   (/search 同义)
   │
   ├─ 鉴权：get_current_user
   │
   ├─ 计算可见性
   │     └─ _get_allowed_and_check
   │
   ├─ 向量检索
   │     └─ _search_audio_segments
   │         └─ vs.similarity_search_with_score
   │
   ├─ 构建 hits
   │     └─ _build_audio_hits
   │         ├─ 去重
   │         ├─ 时间区间校验
   │         ├─ DB 可见性兜底校验
   │         └─ 生成 clip_url
   │
   └─ 返回 AudioSearchResp(hits)


四、音频问答 ask（RAG 热路径核心）

POST /audio/ask
   │
   ├─ 鉴权
   ├─ 解析 question / k
   │
   ├─ 计算可见性
   │     └─ _compute_allowed_visibilities
   │
   ├─ 向量检索
   │     └─ vs.similarity_search_with_score
   │
   ├─ 构建 citations
   │     ├─ 去重
   │     ├─ DB 权限兜底
   │     └─ clip_url
   │
   ├─ 是否有 OPENAI_API_KEY ?
   │     ├─ 否 → 直接返回 citations
   │     └─ 是
   │
   ├─ 构造 RAG prompt
   │     └─ _build_rag_messages
   │
   ├─ LLM 调用
   │     └─ _openai_chat_complete
   │
   └─ 返回 answer + citations


五、音频问答流式 ask/stream（与 ask 的差异点）


POST /audio/ask/stream
   │
   ├─ 前半段：与 /ask 完全一致
   │     ├─ 权限
   │     ├─ 向量检索
   │     └─ citations
   │
   ├─ 构造 RAG messages
   │
   ├─ 流式 LLM
   │     └─ _openai_stream
   │         └─ llm.stream(...)
   │
   └─ SSE 持续输出 token


六、音频片段播放（clip，纯资源路径）

GET /audio/docs/{audio_id}/clip
   │
   ├─ 参数校验 start_ms / end_ms
   ├─ 权限校验（visibility）
   ├─ 裁剪音频
   └─ StreamingResponse





🔥 RAG 热路径（Audio Ask）

目标：
将「用户问题」→「相关音频片段」→「基于片段的可靠回答」

一、整体调用链（精简版）
POST /audio/ask
   │
   ├─ 权限计算（visibility）
   ├─ 向量检索（audio segments）
   ├─ 片段过滤 / 去重 / 权限兜底
   ├─ 构造 RAG Prompt
   ├─ LLM 生成回答
   └─ 返回 answer + citations

二、详细执行顺序（真实热路径）
HTTP Request
   │
   ├─ get_current_user
   │
   ├─ _compute_allowed_visibilities
   │     └─ 计算用户可访问的 visibility（强制包含 public）
   │
   ├─ Vector Search
   │     └─ vs.similarity_search_with_score
   │         └─ 基于 question + visibility 过滤
   │
   ├─ 构建 citations
   │     ├─ metadata 校验（audio_id / segment_id）
   │     ├─ 时间区间校验（start_ms < end_ms）
   │     ├─ 业务级去重（audio + segment + time）
   │     ├─ audio_documents 权限兜底校验
   │     └─ 生成 clip_url
   │
   ├─ 是否配置 OPENAI_API_KEY ?
   │     ├─ 否 → 直接返回 citations
   │     └─ 是
   │
   ├─ _build_rag_messages
   │     ├─ system prompt（约束：只基于片段）
   │     └─ user prompt（问题 + 音频片段上下文）
   │
   ├─ LLM 调用
   │     └─ _openai_chat_complete
   │
   └─ Response
         ├─ answer
         └─ citations（可直接播放）

三、RAG Prompt 结构（核心约束）
System:
  - 只能基于给定音频片段回答
  - 片段不足时明确说“不确定”
  - 回答简洁，必须标注引用 [1][2]...

User:
  - 问题
  - 音频片段上下文（带编号）
  - 明确禁止编造

四、为什么这是「热路径」

🚀 每次用户问答都会走

🚀 向量检索 + LLM = 性能 & 成本核心

🚀 权限、去重、兜底都在这一步完成

🚀 任何 bug 都会直接影响用户体验

五、设计原则（隐含但关键）

向量库 ≠ 权限可信源
→ 最终权限一定走 audio_documents 再校验一遍

先宽搜，再严选
→ fetch_k = min(max(k * 5, k), 50)

clip_url 统一由后端生成
→ 避免前端拼错、权限绕过

六、一句话总结

RAG 热路径 =「向量召回 → 业务过滤 → 权限兜底 → 受控 Prompt → 可追溯回答」


Audio ES 模块职责：
- 存储「音频段」的可搜索文本
- 支持关键词检索 & 向量检索的数据源
- visibility 是最终权限兜底字段
- audio_documents 才是权限事实源


🔥 Audio Segment → ES 索引热路径
1️索引初始化（冷路径 / 兜底）
服务启动 / 首次写入
   │
   ├─ ensure_audio_index
   │     ├─ es.indices.exists
   │     └─ es.indices.create
   │           ├─ mappings（audio_id / segment / text / visibility）
   │           └─ settings（1 shard / 0 replica）
   │
   └─ 索引就绪


作用：保证 ES 中始终存在 audio_segments 索引
性质：冷路径 / 防御性代码

🔥 音频入库 → ES 写入热路径（Ingest）
音频切分完成
   │
   ├─ upsert_audio_segments
   │     │
   │     ├─ ensure_audio_index
   │     │
   │     ├─ 构造 bulk actions
   │     │     ├─ _id = audio_id:segment_idx
   │     │     ├─ start_ms / end_ms
   │     │     ├─ text
   │     │     └─ visibility
   │     │
   │     ├─ helpers.bulk(index)
   │     │     └─ refresh=true
   │     │
   │     └─ 返回写入条数
   │
   └─ ES 中可被检索


作用：把「音频段」变成可搜索的 ES 文档
性质：写路径核心（但不在用户请求热路径）

🔥 ES 关键词搜索热路径（Search / Query）
HTTP /audio/query
   │
   ├─ 权限计算（allowed_visibilities）
   │
   ├─ keyword_search
   │     │
   │     ├─ ensure_audio_index
   │     │
   │     ├─ 构造 ES Query
   │     │     ├─ simple_query_string(text)
   │     │     └─ filter visibility IN (...)
   │     │
   │     ├─ es.search
   │     │
   │     └─ 解析 hits → ESKeywordHit
   │
   └─ 返回关键词命中结果


作用：全文关键词检索（非向量）
性质：用户直接感知的查询热路径之一

🔥 音频删除 / 可见性变更（维护路径）
删除音频对应的所有段
音频删除 / 覆盖
   │
   ├─ delete_by_audio_id
   │     ├─ delete_by_query(term audio_id)
   │     └─ refresh
   │
   └─ ES 中段数据清空

更新音频可见性
音频 visibility 变更
   │
   ├─ update_visibility_by_audio_id
   │     ├─ update_by_query
   │     ├─ painless script
   │     └─ refresh
   │
   └─ 权限即时生效
