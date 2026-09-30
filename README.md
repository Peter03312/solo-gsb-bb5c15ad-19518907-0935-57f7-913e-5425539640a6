# 移调分谱生成器（Transposed Part Generator）

面向小型合奏排练的 Web 应用：上传 MusicXML 总谱，选择一个**有调（pitched）乐器声部**，
填写原乐器与目标乐器各自的「记谱音 → 发声音」有向音程（字母步数 L、半音数 S）以及目标
书写音域，即可生成目标分谱预览并下载移调后的 MusicXML。

- 前端：React 18 + Vite，乐谱预览使用 OpenSheetMusicDisplay
- 后端：FastAPI + lxml（直接操作 MusicXML，最大限度保留原结构）
- 存储：上传的原谱与生成结果保存在服务端本地磁盘（`DATA_DIR`，默认卷 `transpose-data`）；
  表单参数保存在浏览器 `localStorage`

## 一、核心音乐规则

1. **实际发声音高保持不变**：所有音符与和弦音按
   `目标书写 = 原书写 + (L原 − L目标, S原 − S目标)` 换算；
   下载的文件内含正确的 MusicXML `<transpose>`（diatonic / chromatic / octave-change）
   声明，下游软件回放音高与原谱一致。
2. **延音线（tie）两端保持同一书写音高**：终点音符不另加临时升降号；
   未闭合或音高不匹配的延音线会导致整份转换被拒绝。
3. **小节、声部、时值、休止、反复记号等结构不丢失**：仅改动音高、调号与临时升降号，
   其余元素（backup/forward、ending、repeat、dynamics、lyrics、连音线等）原样保留。
4. **调号按音程转换**（含大小调、中途转调），临时升降号依据新调号与同小节同音位
   升降历史重新计算，跨小节自动失效。
5. **超音域只报告、不改八度**：逐音检查目标书写音高，列出小节号与具体音名
   （含「高于上限/低于下限」与边界），不做任何自动八度移动。
6. **遇到以下任一情况，拒绝整份转换，绝不输出部分结果**：
   - 文件损坏、不是 partwise MusicXML（含 opus / timewise / 无法解析的 mxl）；
   - 音程无效（方向矛盾、需要超出重降–重升的变音）；
   - 目标音域无效（下限高于上限、音名无法解析）；
   - 所选声部含无调打击乐 `<unpitched>`；
   - 非传统自定义调号（`key-step/key-alter`）、微分音；
   - 缺少时值/`divisions`、重复声部/小节号、延音线不完整等结构损坏。

## 二、一键启动（Docker Compose，推荐）

要求：Docker 20.10+ 与 Docker Compose v2。镜像内已完成依赖安装与目录初始化。

```bash
docker compose up --build -d
```

启动后访问：

- 应用地址：<http://localhost:8000>
- API 健康检查：<http://localhost:8000/api/health>
- API 文档（Swagger）：<http://localhost:8000/docs>

停止 / 查看日志：

```bash
docker compose down
docker compose logs -f
```

### 端口与配置

在仓库根目录创建 `.env`（或直接导出环境变量）即可覆盖默认值：

```bash
# 主机暴露端口（容器内固定 8000）
HOST_PORT=8000
```

后端支持的环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST_PORT` | `8000` | 仅 Compose 使用，映射到主机的端口 |
| `DATA_DIR` | `/data`（容器）/ `./data`（本地） | 上传与生成文件的本地存储目录，按天清理旧文件 |
| `MAX_UPLOAD_BYTES` | `20971520`（20 MB） | 上传文件大小上限 |
| `CORS_ORIGINS` | localhost:5173/8000 | 允许跨域访问 API 的来源（逗号分隔） |
| `STATIC_DIR` | `/app/frontend/dist` | 后端托管的前端构建产物目录 |

数据通过命名卷 `transpose-data` 持久化；`docker compose down -v` 会连同数据卷一起删除。

## 三、本地开发（不用 Docker）

### 后端（FastAPI，:8000）

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端（Vite，:5173，自动代理 /api → :8000）

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>。若后端不在本机 8000，可设置
`VITE_API_TARGET=http://your-backend:8000` 后再启动。

生产模式下，前端 `npm run build` 的产物由 FastAPI 在 `/` 直接托管（见 `STATIC_DIR`）。

### 运行测试

```bash
cd backend
python -m pytest -q
```

覆盖音程/调号/临时号理论、发声音高守恒、和弦、延音线配对、休止与反复保留、
超音域清单、无调打击乐与损坏文件拒绝、压缩 .mxl、HTTP 端到端流程。

## 四、使用步骤

1. 上传 `.musicxml` / `.xml`（partwise）或压缩的 `.mxl`。
2. 选择一个有调乐器声部（含无调打击乐的声部会被标记且不可选）。
3. 选择/填写原乐器与目标乐器的记谱→发声音音程：
   - B♭ 小号：写 C4 发 B♭3 → L = −1，S = −2
   - E♭ 中音萨克斯：写 C4 发 E♭3 → L = −5，S = −9
   - F 圆号：写 C5 发 F4 → L = −4，S = −7
   - 短笛：写 C5 发 C4（发声比记谱低八度）→ L = −7，S = −12
   - 低音提琴：写 C3 发 C4（发声比记谱高八度）→ L = 7，S = 12
4. 填写目标书写音域上下限（如 E3 / C6，支持 `# ♯ b ♭ x ## bb` 与八度数字）。
5. 点击「生成目标分谱」：成功则展示乐谱预览与文件元信息，可下载
   `声部名_标注.musicxml`；失败时给出原因（超音域时另附小节/音高清单），且不生成文件。

## 五、目录结构

```
backend/
  app/
    main.py          # FastAPI 路由（上传/分析/转调/下载/静态托管）
    transposer.py    # 结构校验 + 移调引擎（失败即整体拒绝）
    theory.py        # 音程、调号、临时升降号、音名解析等纯理论
    musicxml.py      # XML/.mxl 解析与声部扫描
    storage.py       # 本地磁盘存储与定期清理
  tests/             # pytest（理论 + 引擎 + API）
frontend/
  src/
    App.jsx          # 四步式界面
    ScorePreview.jsx # OpenSheetMusicDisplay 预览
    presets.js       # 常见移调乐器音程预设
    api.js / useLocalStorage.js / styles.css
Dockerfile           # 多阶段：node 构建前端 + python 运行后端
docker-compose.yml   # 一键启动 + 数据卷 + 健康检查
```
