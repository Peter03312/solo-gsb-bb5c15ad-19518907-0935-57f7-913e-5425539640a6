# 移调分谱生成器（Transposed Parts Generator）

供小型合奏排练使用的 **MusicXML 移调分谱** Web 应用。上传总谱、选择一个有调乐器声部、
填写原乐器与目标乐器各自“记谱音 → 实际发声音”的有向音程与目标书写音域，
即可在浏览器中预览并下载移调后的单声部 MusicXML。

- 前端：React 18 + Vite + [OpenSheetMusicDisplay](https://github.com/opensheetmusicdisplay/opensheetmusicdisplay)（本地渲染预览）
- 后端：FastAPI + lxml（不依赖任何外部制谱服务，全部本地计算）
- 存储：不上传/落盘任何用户文件；参数、历史与最近结果保存在浏览器 **localStorage**
- 部署：单镜像多阶段构建，`docker compose up --build` 一键启动

---

## 1. 快速开始（推荐：Docker Compose）

```bash
# 在仓库根目录
docker compose up --build
```

启动后用浏览器访问：

- **应用地址：http://localhost:8000**

停止：`Ctrl+C`（或 `docker compose down`）。

### 修改端口等配置

复制环境变量模板并按需修改：

```bash
cp .env.example .env
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TRANSPOSER_PORT` | `8000` | 宿主机暴露端口（容器内固定 8000） |
| `CORS_ORIGINS` | `*` | 允许跨域来源，多个用逗号分隔 |
| `MAX_UPLOAD_BYTES` | `20971520` | 单文件上传上限（20MB） |

例如想用 9000 端口：`TRANSPOSER_PORT=9000 docker compose up --build`，
然后访问 http://localhost:9000。

---

## 2. 使用步骤

1. **上传** MusicXML（支持未压缩 `.musicxml/.xml` 与压缩 `.mxl`，需为 partwise、MusicXML 2.0+）。
2. **选择声部**：下拉列出全部声部及音符数；含无调打击乐的声部会被禁用/拒绝。
3. **填写原乐器移调音程**（记谱音 → 发声音）：
   - 可直接选预设（Bb 小号、Eb 中音萨克斯、F 圆号等），或自定义。
   - 两个字段：
     - **有向字母步数**：记谱音到发声音跨越的音级数（C→D=1，C→高八度 C=7），下行取负。
     - **有向半音数**：同一有向音程包含的半音数，下行取负。
   - 例：Bb 小号记谱 D4 实际发 C4 → 字母 `-1`、半音 `-2`；
     Eb 中音萨克斯记谱 A3 实际发 C4 → 字母 `+2`、半音 `+3`；
     低音提琴记谱比实高高八度 → 字母 `-7`、半音 `-12`。
   - 若文件第一小节带有 `<transpose>` 标记，后端会校验所填原乐器参数与其一致，不一致即拒绝。
4. **填写目标乐器移调音程**（同上含义）。
5. **填写目标书写音域**（如中音萨克斯 `Bb2`–`F#5`，支持 `#`、`x`、`b`、`bb` 记号）。
6. 点击“生成移调分谱”：右侧预览，确认后“下载 MusicXML”。

---

## 3. 转换保证与拒绝规则

应用对**结构与音高的完整性**采取严格策略：任何无法保证的情况都会**拒绝整份转换，
绝不输出半成品**。

### 始终保证

- 所有音符与和弦的**实际发声音高**与原谱一致（输出文件写入目标乐器的
  `<transpose>` 标记，下游播放/制谱软件据此还原音高）；
- 移调按统一有向音程进行，**不擅自移动八度**；
- **延音线（tie）两端保持同一书写音高**（跨小节、链状延音同样处理）；
- **小节、声部/voice、时值（duration/type/附点/连音）、休止、反复记号、房子结尾**
  等结构原样保留（转换后做结构指纹比对自检）；
- **调号**按音程（含大小调模式）转换；**临时升降/还原号**随音符重算，
  并正确处理同一小节内同音级的临时号持续与还原；
- 和弦标记 `<harmony>` 的根音/低音同步移调。

### 超出音域

- 任何移调后音高落在目标书写音域之外时，**拒绝转换**，并列出每个越界音的
  **小节号与目标记谱音高**；不会自动升降八度凑入音域。

### 直接拒绝（示例）

- 文件为空、XML 损坏、不是 MusicXML、timewise 格式、MusicXML 1.x、opus 索引；
- 音程（字母步数/半音数）方向矛盾或无法用常规记谱拼写（要求两升/两降以上）；
- 目标音域无效（格式错误或下限高于上限）；
- 所选声部含**无调打击乐（unpitched）**、微音分（非整数 alter）、非常规变音记号；
- 声部在曲中**更换移调乐器**（多个 `<transpose>`）、按谱表分别设置调号、
  自定义调号变音（key-accidental）、特殊谱表等无法完整保留的结构；
- 源文件本身存在未闭合/不配对或两端音高不一致的延音线。

---

## 4. 本地开发（不用 Docker）

### 后端

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload --port 8000
```

API：

- `GET  /api/health` 健康检查
- `POST /api/inspect`（multipart：`file`）→ 声部列表
- `POST /api/transpose`（multipart：`file, part_id, src_diatonic, src_chromatic,
  dst_diatonic, dst_chromatic, range_low, range_high`）→ `{filename, meta, musicxml_base64}`

运行后端测试（自动生成合成 MusicXML 夹具）：

```bash
cd backend
PYTHONPATH=. python3 -m pytest -q
```

### 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 ，/api 自动代理到 8000
```

生产构建：`npm run build`（产物在 `frontend/dist`，镜像构建即使用该目录）。

可用的前端环境变量：

| 变量 | 说明 |
| --- | --- |
| `VITE_API_BASE` | API 前缀（默认空字符串，同源/走代理） |
| `VITE_BACKEND_URL` | 仅 `npm run dev` 代理目标，默认 `http://localhost:8000` |

---

## 5. 目录结构

```
.
├── Dockerfile                # 多阶段：Node 构建前端 + Python 运行后端并托管静态文件
├── docker-compose.yml        # 一键启动
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI 路由 / 静态托管
│   │   ├── service.py        # 编排：校验 → 移调 → 自检 → 序列化
│   │   ├── transposer.py     # 调号/临时号/tie/harmony/结构处理
│   │   ├── intervals.py      # 有向音程、五度圈、音域运算
│   │   ├── verify.py         # 转换后自检（结构指纹 + 发声 MIDI + tie）
│   │   └── mx.py             # MusicXML/.mxl 解析与异常定义
│   ├── requirements.txt
│   └── tests/                # 合成夹具 + 端到端测试
└── frontend/
    ├── src/（React、OSMD 预览、本地存储、客户端校验）
    └── vite.config.js
```

---

## 6. 说明与限制

- 本工具定位为**排练用移调分谱**：音高、节奏、反复等结构严格保真；
  目标乐器谱号/指法等版式元素不在移调范畴，输出沿用源谱谱号，
  可在制谱软件中一键调整。
- 所有解析均禁用外部 DTD/实体（离线、防 XXE），并对压缩包大小/条目数做了限制。
- 数据不出本机：后端处理的是请求中的文件副本、不写盘；前端历史仅存于浏览器。
