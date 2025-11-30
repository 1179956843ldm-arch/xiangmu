# Enterprise Knowledge Base Assistant

## 项目简介
Enterprise Knowledge Base Assistant是一个企业知识库管理系统，旨在帮助企业高效管理和利用内部知识资源，提升组织协作效率和知识共享能力。

## 项目结构
```
enterprise-kb-assistant/
├── .venv/                # 虚拟环境
├── app/                  # 应用程序主目录
├── data/                 # 数据目录
│   ├── chroma/           # Chroma向量数据库
│   ├── docs/             # 文档存储目录
│   └── tests/            # 测试数据
├── tests/                # 测试目录
├── README.md             # 项目说明文档
└── requirements.txt      # 项目依赖
```

## 主要功能
- 文档管理：支持上传、存储、分类和检索各种格式的文档
- 智能搜索：基于向量数据库的语义搜索功能
- 知识问答：基于企业知识库的智能问答系统
- 用户权限管理：支持不同角色的权限控制

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
