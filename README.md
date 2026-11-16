# Olist 电商分析与自然语言查询

使用 Olist 公开电商数据，完成经营、品类、用户复购和物流评价分析，并构建一个自然语言查询原型。用户输入问题后，模型生成 PostgreSQL 查询；程序检查语句，展示 SQL，由用户确认后通过受限账号执行并展示结果。

本项目为学习用途的原型：它通过提示词生成 SQL，尚不是具备自主规划、工具选择与纠错的完整 Agent；提示词和 SQL 检查也不能保证业务语义正确。

## 功能与技术

- PostgreSQL：多表关联、CTE、窗口函数（`LAG`、`RANK`、`ROW_NUMBER` 和 `LEAD`）、分析视图与数据检查。
- Python + 百炼兼容接口：自然语言生成 SQL；SQLGlot 检查单条查询和允许访问的视图。
- Streamlit：输入问题、展示 SQL、确认后执行和显示结果。
- 测试：使用人工编写的参考 SQL 比较查询结果，并检查无法回答时的拒答行为。

## 数据与口径

数据来源：[Olist Brazilian E-Commerce Public Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)。数据文件需自行下载至 `data/`，使用和分享时遵守数据集页面的许可。此项目使用 7 份 CSV：订单、客户、商品明细、支付、商品、评价及品类翻译；地理和卖家文件暂未使用。

- 数据覆盖 2016–2018 年。默认按下单时间和已交付订单分析。
- 商品销售额为商品明细 `price` 之和，不含运费；支付金额单独统计。
- 商品明细和支付均可能一单多行，订单级分析先分别按订单汇总，避免关联放大金额。
- 用户分析基于 `customer_unique_id`。月内复购表示同一用户同月有两笔及以上已交付订单；月度用户数不能直接相加得到跨月去重用户数。
- 延迟按实际交付日期是否晚于预计日期判断。订单可缺少评分；每单取最新一条有回答时间、评分为 1–5 的评价。评分差异只说明关联。
- 数据不包含完整的浏览行为和广告成本；当前授权视图不支持跨月去重用户查询。数据质量、缺失值与口径见 `database_guide.txt`。

## 环境

- Windows、Docker Desktop、PostgreSQL 17；项目实际测试使用 Python 3.13。
- 百炼北京地域 API Key 和可用额度。模型请求会产生 Token 用量，免费额度和价格以服务商控制台为准。
- 安装依赖：`py -3 -m venv .venv`，然后执行 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`。

## 数据库：新环境复现

**下面只针对全新的空数据库。已有项目数据库不要再次运行 `sql/setup.sql`，避免重复建表或导入。** 脚本中的 `/workspace/data` 需要正确挂载到包含 CSV 文件的项目目录。导入脚本在事务中执行；如有错误请先确认问题，不要反复尝试。

在项目根目录放好 CSV 后，使用一个全新 Docker 容器和数据卷（如容器名、数据卷或端口已存在，请先检查并调整）：

```powershell
docker run -d `
  --name olist-postgres `
  -e POSTGRES_USER=olist_admin `
  -e POSTGRES_PASSWORD=olist_local_123 `
  -e POSTGRES_DB=olist `
  -p 127.0.0.1:5433:5432 `
  -v olist-db-data:/var/lib/postgresql/data `
  -v "${PWD}:/workspace:ro" `
  postgres:17
```

等待数据库启动后执行（初始化过程可能需要一点时间）：

```powershell
docker exec -it olist-postgres psql -U olist_admin -d olist -v ON_ERROR_STOP=1 -f /workspace/sql/setup.sql
```

然后进入管理员 SQL 界面，创建本机专用的低权限登录账号。自行设置练习密码，勿提交密码或对外公开：

```powershell
docker exec -it olist-postgres psql -U olist_admin -d olist
```

```sql
CREATE ROLE olist_reader WITH LOGIN PASSWORD '替换为你设置的本地密码';
\i /workspace/sql/grants.sql
```

现有数据库如果已创建角色和授权，则不需要重复创建。`sql/analysis.sql` 提供只读分析示例；`sql/setup.sql` 的建表、数据导入与视图逻辑已在独立事务中检查并回滚，未覆盖既有数据。

## 本机运行

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

打开终端显示的 Local URL；输入百炼 API Key 和问题，检查 SQL，再输入数据库只读账号密码执行。API Key 和密码运行时输入，不写入源代码，但页面会话期间输入控件可能暂存其值。此页面仅供本机演示，不应直接对公网部署。

命令行版：`.\.venv\Scripts\python.exe ask_database.py`。停止页面使用 PowerShell 中的 `Ctrl + C`。

## 测试与限制

运行 `.\.venv\Scripts\python.exe evaluate_agent.py`。目前有 11 道题：7 道可回答、4 道应拒答。每次最多发起 11 次模型调用，执行生成 SQL 前需人工确认。比较会关注行列顺序；测试记录默认保存在本地，并被 `.gitignore` 排除。

2026-11-16 的一次人工确认测试中，11 题均通过（7/7 可回答，4/4 拒答）。该结果仅反映这一组小样本和一次运行，不代表总体准确率。测试结果依赖模型、数据、提示词和数据库状态，应在不同问题和多次运行下继续验证。

另一次 280 题模板化测试中，279 题参与评分、1 题跳过：总计 249/279 通过；其中可回答题 209/239 结果正确，应拒答题 40/40 正确拒答。30 个未通过案例包括 25 个查询取消（当前执行器设置 5 秒超时）和 5 个结果不一致。将其中两个被取消的 SQL 以 20 秒超时单独重放后，两题分别用时约 10.81 和 11.34 秒，结果均与参考答案一致；这不能代表其他超时题也一定正确。题目由有限模板按月份扩展，统计是一次端到端测试结果，不是对模型通用准确率的估计。

安全限制包括视图白名单、单条 SELECT 检查、受限账号、只读事务、查询超时与结果行数限制。它们适合本地练习，不能作为生产环境完整的安全边界；生成 SQL 仍须人工核查。当前实现也不支持 JOIN、WITH 和子查询，业务分析使用预先建立的视图。
