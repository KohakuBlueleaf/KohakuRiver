# KohakuRiver

[![授權條款: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Docs](https://img.shields.io/badge/docs-riverdoc.kohaku--lab.org-blue)](https://riverdoc.kohaku-lab.org)
[![en](https://img.shields.io/badge/lang-en-red.svg)](./README.md)
[![中文](https://img.shields.io/badge/lang-中文-green.svg)](./README.zh.md)

<p align="center">
  <img src="image/logo.svg" alt="KohakuRiver" width="400">
</p>

<p align="center">
  <b>為小型團隊與研究實驗室打造的自架式叢集管理工具。</b><br>
  透過 Docker 容器、QEMU/KVM 虛擬機、VXLAN overlay 網路與 GPU 直通，<br>
  在多個運算節點間分配任務與持久性 VPS 工作階段。
</p>

<p align="center">
  <a href="https://riverdoc.kohaku-lab.org">文件</a> &middot;
  <a href="#快速入門">快速入門</a> &middot;
  <a href="#cli-參考">CLI 參考</a>
</p>

---

## 概觀

擁有 3 到 20 台運算節點的小型團隊常常面臨尷尬的處境——機器太多，用 SSH 腳本手動管理太累；機器太少，部署 Slurm 或 Kubernetes 又太過頭。KohakuRiver 把你的叢集當成一台大電腦：送出一個指令或啟動一個 VPS，它就會在對的節點上用對的資源來執行。

> KohakuRiver 裡的 Docker 扮演的是可攜式虛擬環境的角色。設定一次、打包成 tarball，所有節點就會自動同步同一套環境。

### 核心功能

- **命令任務** — 一次性批次執行，擷取 stdout/stderr
- **VPS 工作階段** — 持久性互動式環境，支援 SSH、終端機與 Port 轉發
- **雙後端** — Docker 容器用於輕量任務，QEMU/KVM 虛擬機用於完整硬體隔離
- **GPU 支援** — Docker 用 NVIDIA Container Toolkit，虛擬機用 VFIO 直通
- **Overlay 網路** — VXLAN L3 星狀拓撲，不同節點上的容器可直接通訊
- **Tunnel 系統** — 基於 WebSocket 的終端機與 Port 轉發，不需要 Docker port mapping
- **Web 儀表板** — Vue.js 介面，叢集管理、監控與終端機存取一站搞定
- **終端機 TUI** — 全螢幕儀表板與 IDE 模式，內建檔案樹和整合終端機
- **認證系統** — 角色分級（admin/operator/user）、API token、邀請制註冊

---

## 截圖

### Web 儀表板

<table>
<tr>
<td width="50%">

**叢集總覽**

![Cluster Overview](image/README/1770620187904.png)

</td>
<td width="50%">

**節點監控**

![Node Monitoring](image/README/1770620223368.png)

</td>
</tr>
</table>

<table>
<tr>
<td width="25%">

**任務管理**

![Task Management](image/README/1770620250783.png)

</td>
<td width="25%">

**建立任務**

![1770621295326](image/README/1770621295326.png)

</td>
<td width="25%">

**VPS 管理**

<img src="image/README/1770620270764.png">

</td>
<td width="25%">

**建立 VPS**

<img src="image/README/1770620338639.png">

</td>
</tr>
</table>

### 終端機 TUI

<table>
<tr>
<td width="50%">

**TUI 儀表板**

![1770657989063](image/README/1770657989063.png)
![1770658004247](image/README/1770658004247.png)

</td>
<td width="50%">

**IDE 模式**

![1770656962491](image/README/1770656962491.png)

</td>
</tr>
</table>

---

## 架構

```
                  ┌──────────┐   ┌──────────────────────┐
                  │   CLI    │   │    Web 儀表板         │
                  └────┬─────┘   └──────────┬───────────┘
                       │                    │
                       ▼                    ▼
┌────────────────────────────────────────────────────────────┐
│                  Host 伺服器 (:8000)                       │
│                                                            │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐  │
│  │  FastAPI  │ │   任務    │ │  Overlay  │ │ SSH Proxy │  │
│  │   API     │ │   排程器  │ │   管理器  │ │  (:8002)  │  │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘  │
│  ┌────────────┐ ┌────────────────────────────────────┐     │
│  │   認證     │ │  SQLite 資料庫 (Peewee ORM)        │     │
│  │   服務     │ │  tasks, nodes, users, auth         │     │
│  └────────────┘ └────────────────────────────────────┘     │
└────────────────────────────┬───────────────────────────────┘
                             │  HTTP + VXLAN
            ┌────────────────┴────────────────┐
            │                                 │
┌───────────▼────────────────┐  ┌─────────────▼──────────────┐
│  Runner 節點 A (:8001)     │  │  Runner 節點 B (:8001)     │
│                            │  │                            │
│  ┌──────────────────────┐  │  │  ┌──────────────────────┐  │
│  │  Runner Agent        │  │  │  │  Runner Agent        │  │
│  │  (FastAPI)           │  │  │  │  (FastAPI)           │  │
│  └──────────────────────┘  │  │  └──────────────────────┘  │
│                            │  │                            │
│  ┌──────────┐ ┌──────────┐ │  │  ┌──────────┐ ┌──────────┐ │
│  │  Docker  │ │  Tunnel  │ │  │  │  Docker  │ │   QEMU   │ │
│  │  Engine  │ │  Server  │ │  │  │  Engine  │ │   /KVM   │ │
│  └──────────┘ └──────────┘ │  │  └──────────┘ └──────────┘ │
│  ┌──────────┐ ┌──────────┐ │  │  ┌──────────┐ ┌──────────┐ │
│  │   VPS    │ │  VXLAN   │ │  │  │  Tunnel  │ │  VXLAN   │ │
│  │   管理器 │ │  Agent   │ │  │  │  Server  │ │  Agent   │ │
│  └──────────┘ └──────────┘ │  │  └──────────┘ └──────────┘ │
│                            │  │                            │
│  ┌──────┐ ┌──────┐        │  │  ┌──────┐ ┌──────┐        │
│  │VPS 1 │ │VPS 2 │        │  │  │VPS 3 │ │ VM 1 │        │
│  └──────┘ └──────┘        │  │  └──────┘ └──────┘        │
└────────────────────────────┘  └────────────────────────────┘
                             │
            ┌────────────────▼────────────────┐
            │   共享儲存空間（選用）           │
            │   NFS / Samba / SSHFS           │
            └─────────────────────────────────┘
```

| 層級 | 角色 |
|------|------|
| **Host** (:8000) | 中央控制平面。任務排程、節點管理、overlay hub、SSH/WebSocket proxy、SQLite 資料庫。 |
| **Runner** (:8001) | 運算節點 agent。在 Docker/QEMU 中執行任務、監控資源、執行 tunnel server、管理 overlay agent。 |
| **容器 / 虛擬機** | 工作負載。Docker 用於輕量任務，QEMU/KVM 用於完整隔離與 GPU 直通。 |
| **共享儲存** | （選用）NFS/Samba/SSHFS。簡化 tarball 分發。各節點路徑可不同。使用 registry 映像檔或虛擬機時不需要。 |

---

## 快速入門

### 前置需求

- Python >= 3.10
- Host 和 Runner 節點皆安裝 Docker Engine
- （選用）共享檔案系統、NVIDIA 驅動程式 + Container Toolkit、QEMU/KVM + IOMMU

### 安裝

```bash
git clone https://github.com/KohakuBlueleaf/KohakuRiver.git
cd KohakuRiver
pip install .

# 含 GPU 監控
pip install ".[gpu]"
```

### 設定

```bash
kohakuriver init config --generate
```

編輯 `~/.kohakuriver/host_config.py`：
```python
HOST_REACHABLE_ADDRESS = "192.168.1.100"  # Runner 可連到的 IP
SHARED_DIR = "/mnt/cluster-share"         # 共享儲存路徑（選用）
```

編輯 `~/.kohakuriver/runner_config.py`：
```python
HOST_ADDRESS = "192.168.1.100"            # Host IP
SHARED_DIR = "/mnt/cluster-share"         # 同一個共享儲存
```

### 啟動

```bash
# 在 Host 機器上
kohakuriver.host

# 在每個 Runner 節點上
kohakuriver.runner
```

正式環境建議用 systemd：
```bash
kohakuriver init service --host     # 在 Host 上
kohakuriver init service --runner   # 在 Runner 上
sudo systemctl enable --now kohakuriver-host
sudo systemctl enable --now kohakuriver-runner
```

### 第一個任務

```bash
kohakuriver task submit -t mynode -- echo "Hello from the cluster!"
kohakuriver task logs <task_id>
```

### 第一個 VPS

```bash
kohakuriver vps create -t mynode -c 4 -m 8G --ssh
kohakuriver vps connect <task_id>          # SSH
kohakuriver connect <task_id>              # WebSocket 終端機
kohakuriver connect <task_id> --ide        # TUI IDE
```

---

## 功能特色

### 容器即可攜環境

在 Host 上建立 Docker 容器、互動式自訂、打包成 tarball。所有 Runner 自動同步。也可以直接從任何 Docker registry 拉取映像檔。

```bash
kohakuriver docker container create python:3.12-slim my-env
kohakuriver docker container shell my-env        # 互動式自訂
kohakuriver docker tar create my-env             # 打包分發
```

### 資源管理

```bash
# 4 核心、8GB 記憶體、在 alpha 節點上使用 GPU 0 和 1
kohakuriver task submit -t alpha::0,1 -c 4 -m 8G --container my-env -- python train.py
```

- **CPU** — 指定核心數與綁定、NUMA 綁定（`-t node:numa_id`）
- **記憶體** — 每個任務的記憶體限制（`-m 8G`）
- **GPU** — 以索引指定（`-t node::0,1`），Docker 用 NVIDIA Container Toolkit，虛擬機用 VFIO
- **多目標** — 一個指令送出到多個節點/GPU

### QEMU/KVM 虛擬機

完整的虛擬機加上 VFIO GPU 直通。Cloud-init 自動設定 SSH 金鑰、網路和 NVIDIA 驅動程式。

```bash
kohakuriver qemu check                                          # 檢查硬體支援
kohakuriver vps create --backend qemu -t mynode::0 --vm-memory 16384 -c 8 --ssh
```

### Overlay 網路

VXLAN L3 星狀拓撲，Host 作為中央路由器。設定 `OVERLAY_ENABLED=True` 並開放 UDP 4789——tunnel 建立、子網段配置、IP 保留、路由和防火牆規則都會自動處理。

```
              Host (10.128.0.1/12)
                    │
         ┌─────────┴──────────┐
    VXLAN VNI=101        VXLAN VNI=102
         │                    │
   Runner 1              Runner 2
   10.128.64.0/18        10.128.128.0/18
```

最多支援 63 個 Runner，每個約 16,380 個 IP（可調整）。

### 免 Port Mapping 存取

容器內的 Rust tunnel client（Tokio + Tungstenite）透過 WebSocket tunnel 提供存取：

```bash
kohakuriver connect <task_id>              # 完整 TTY 終端機（vim、htop 都能用）
kohakuriver connect <task_id> --ide        # TUI IDE，含檔案樹
kohakuriver forward <task_id> 8888         # Port 轉發（Jupyter 等）
kohakuriver forward <task_id> 5353 --proto udp
kohakuriver vps connect <task_id>          # 透過 Host proxy 的 SSH
```

不會有 port 衝突。穿越防火牆沒問題。容器重啟後仍可連線。

### 快照

Docker VPS 支援快照——停止時自動建立快照、可手動建立、重啟時還原、可設定保留數量（預設每個 VPS 保留 3 份）。

### 認證

支援 session 和 token 兩種認證方式，角色分級（admin、operator、user）。邀請制註冊。API token 供 CLI 與自動化使用。

---

## Web 儀表板

Vue.js 前端提供叢集總覽、任務/VPS 管理、Docker 環境管理、網頁終端機（xterm.js）、GPU 監控（Plotly.js）與管理員面板。

```bash
cd src/kohakuriver-manager
npm install
npm run dev      # port 5173
npm run build    # 正式環境建置
```

---

## CLI 參考

### 任務

```bash
kohakuriver task submit [OPTIONS] -- CMD    # 送出命令任務
kohakuriver task list                       # 列出任務
kohakuriver task status <id>                # 詳細狀態
kohakuriver task logs <id>                  # stdout（--stderr、--follow）
kohakuriver task kill <id>                  # 終止執行中的任務
kohakuriver task pause <id>                 # 暫停
kohakuriver task resume <id>               # 恢復
kohakuriver task watch <id>                # 即時監控
```

<details>
<summary>送出任務選項</summary>

| 旗標 | 說明 |
|------|------|
| `-t, --target NODE[::GPU,GPU]` | 目標節點，可選 NUMA（`:numa`）和 GPU（`::0,1`） |
| `-c, --cores N` | CPU 核心數（0 = 不限） |
| `-m, --memory SIZE` | 記憶體限制（例如 `8G`、`512M`） |
| `--container NAME` | 容器環境名稱 |
| `--image NAME` | Docker registry 映像檔（替代 tarball） |
| `--privileged` | 以 Docker `--privileged` 執行 |
| `--mount SRC:DST` | 額外的 bind mount |
| `--wait` | 等待任務完成 |

</details>

### VPS

```bash
kohakuriver vps create [OPTIONS]            # 建立 VPS
kohakuriver vps list                        # 列出實例（--all 顯示已停止的）
kohakuriver vps status <id>                 # 詳細狀態
kohakuriver vps stop <id>                   # 停止（保留狀態）
kohakuriver vps restart <id>                # 重啟
kohakuriver vps pause <id> / resume <id>    # 暫停 / 恢復
kohakuriver vps connect <id>                # 透過 proxy SSH 連線
```

<details>
<summary>VPS 選項</summary>

| 旗標 | 說明 |
|------|------|
| `--backend docker\|qemu` | 工作負載後端（預設：docker） |
| `--ssh` | 啟用 SSH 存取 |
| `--gen-ssh-key` | 產生 SSH 金鑰對 |
| `--public-key-file PATH` | SSH 公鑰檔案 |
| `--vm-memory MB` | 虛擬機記憶體 MB（僅 QEMU，預設：4096） |
| `--vm-disk GB` | 虛擬機磁碟 GB（僅 QEMU，預設：20） |
| `--vm-image NAME` | 基礎虛擬機映像檔（僅 QEMU，預設：ubuntu-22.04） |

</details>

### 存取與終端機

```bash
kohakuriver connect <id>                    # WebSocket 終端機（完整 TTY）
kohakuriver connect <id> --ide              # TUI IDE，含檔案樹
kohakuriver forward <id> <port>             # Port 轉發
kohakuriver forward <id> <port> -l <local>  # 自訂本機 port
kohakuriver forward <id> <port> --proto udp # UDP 轉發
kohakuriver terminal                        # TUI 儀表板
```

### 節點

```bash
kohakuriver node list                       # 列出節點（--status online|offline）
kohakuriver node status <hostname>          # 節點詳情
kohakuriver node health [hostname]          # 健康狀態指標
kohakuriver node summary                    # 叢集摘要
kohakuriver node overlay                    # overlay 網路狀態
```

### Docker

```bash
kohakuriver docker container list           # 列出 Host 容器
kohakuriver docker container create IMG NAME # 從映像檔建立
kohakuriver docker container shell NAME     # 互動式 shell
kohakuriver docker container start NAME     # 啟動
kohakuriver docker container stop NAME      # 停止
kohakuriver docker container delete NAME    # 刪除
kohakuriver docker tar list                 # 列出 tarball
kohakuriver docker tar create NAME          # 建立 tarball
kohakuriver docker tar delete NAME          # 刪除 tarball
kohakuriver docker images                   # 列出 Runner 上的映像檔
```

<details>
<summary>QEMU/KVM、認證、SSH、設定</summary>

**QEMU/KVM**

```bash
kohakuriver qemu check                      # 檢查 KVM、IOMMU、VFIO GPU
kohakuriver qemu image create               # 建立基礎虛擬機映像檔
kohakuriver qemu image list                 # 列出基礎映像檔
kohakuriver qemu instances                  # 列出虛擬機實例
kohakuriver qemu cleanup <id>               # 刪除虛擬機實例
kohakuriver qemu acs-override               # 套用 ACS override
```

**認證**

```bash
kohakuriver auth login                      # 登入
kohakuriver auth logout                     # 登出（--revoke 撤銷 token）
kohakuriver auth status                     # 目前認證狀態
kohakuriver auth token list                 # 列出 API token
kohakuriver auth token create <name>        # 建立 token
kohakuriver auth token revoke <id>          # 撤銷 token
```

**SSH**

```bash
kohakuriver ssh connect <id>                # 透過 proxy SSH 連到 VPS
kohakuriver ssh config                      # 產生所有 VPS 的 SSH config
```

**設定**

```bash
kohakuriver init config --generate          # 產生設定檔
kohakuriver init service --host             # 建立 Host systemd 服務
kohakuriver init service --runner           # 建立 Runner systemd 服務
kohakuriver config show                     # 顯示目前設定
```

</details>

---

## 設定

設定檔是放在 `~/.kohakuriver/` 的 Python 模組。用 `kohakuriver init config --generate` 產生。

<details>
<summary>Host 設定（<code>~/.kohakuriver/host_config.py</code>）</summary>

| 設定項 | 預設值 | 說明 |
|--------|--------|------|
| `HOST_REACHABLE_ADDRESS` | `"127.0.0.1"` | Runner 和用戶端用來連到 Host 的 IP/主機名稱 |
| `HOST_PORT` | `8000` | API 伺服器 port |
| `HOST_SSH_PROXY_PORT` | `8002` | SSH proxy port |
| `SHARED_DIR` | `"/mnt/cluster-share"` | 共享儲存路徑 |
| `DB_FILE` | `"cluster_management.db"` | SQLite 資料庫路徑 |
| `OVERLAY_ENABLED` | `False` | 啟用 VXLAN overlay 網路 |
| `DEFAULT_CONTAINER_NAME` | `"kohakuriver-base"` | 預設容器環境 |
| `HEARTBEAT_INTERVAL_SECONDS` | `5` | Runner 心跳間隔 |
| `HEARTBEAT_TIMEOUT_FACTOR` | `6` | 心跳逾時次數（超過視為離線） |
| `TASKS_PRIVILEGED` | `False` | 以 `--privileged` 執行容器 |

</details>

<details>
<summary>Runner 設定（<code>~/.kohakuriver/runner_config.py</code>）</summary>

| 設定項 | 預設值 | 說明 |
|--------|--------|------|
| `HOST_ADDRESS` | `"127.0.0.1"` | Host 伺服器位址 |
| `HOST_PORT` | `8000` | Host 伺服器 port |
| `SHARED_DIR` | `"/mnt/cluster-share"` | 共享儲存路徑（可與 Host 不同） |
| `LOCAL_TEMP_DIR` | `"/tmp/kohakuriver"` | 本機暫存目錄 |
| `OVERLAY_ENABLED` | `False` | 啟用 VXLAN overlay 網路 |
| `TUNNEL_ENABLED` | `True` | 啟用 tunnel server |
| `VM_IMAGES_DIR` | `"~/.kohakuriver/vm-images"` | QEMU 基礎映像檔目錄 |
| `VM_DEFAULT_MEMORY_MB` | `4096` | 虛擬機預設記憶體 |
| `VM_ACS_OVERRIDE` | `False` | 啟用 IOMMU group 的 ACS override |

</details>

<details>
<summary>環境變數</summary>

| 變數 | 說明 |
|------|------|
| `KOHAKURIVER_HOST` | Host 伺服器位址（供 CLI 使用） |
| `KOHAKURIVER_PORT` | Host 伺服器 port（供 CLI 使用） |
| `KOHAKURIVER_SSH_PROXY_PORT` | SSH proxy port（供 CLI 使用） |

</details>

---

## KohakuRiver 適合與不適合的場景

| KohakuRiver 適合⋯⋯ | KohakuRiver 不適合⋯⋯ |
|---|---|
| 小型叢集（3-20 節點） | 大規模 HPC（Slurm、PBS） |
| 命令任務與互動式 VPS 工作階段 | 多服務編排（Kubernetes） |
| Docker 容器作為可攜環境 | 複雜的 CI/CD 流程 |
| 獨立任務與批次送出 | DAG 工作流程編排（Airflow、Prefect） |
| 研究實驗室、家用實驗室、小型團隊 | 多租戶正式環境 |
| 簡單分配的 GPU 工作負載 | 進階 GPU 排程（MIG、time-slicing） |

---

## 專案結構

```
src/
├── kohakuriver/              # Python 後端
│   ├── host/                 # Host 伺服器（FastAPI :8000）
│   ├── runner/               # Runner agent（FastAPI :8001）
│   ├── cli/                  # CLI（Typer + Rich + Textual）
│   ├── db/                   # Peewee ORM 資料模型
│   ├── docker/               # Docker client 封裝
│   ├── qemu/                 # QEMU/KVM + VFIO + cloud-init
│   ├── models/               # Pydantic 請求/回應模型
│   └── utils/                # 共用工具、設定
├── kohakuriver-manager/      # Vue.js Web 儀表板
├── kohakuriver-tunnel/       # Rust tunnel client
└── kohakuriver-doc/          # 文件網站
```

## 技術堆疊

| 層級 | 技術 |
|------|------|
| **後端** | Python 3.10+, FastAPI, Uvicorn, Peewee ORM, SQLite, pyroute2 |
| **CLI** | Typer, Rich, Textual |
| **前端** | Vue.js 3, Vite, Element Plus, Pinia, xterm.js, Plotly.js |
| **Tunnel** | Rust, Tokio, Tungstenite |
| **虛擬機** | QEMU/KVM, VFIO, cloud-init, virtio-9p |
| **認證** | bcrypt, session cookies, API tokens |

## 文件

完整文件：**[riverdoc.kohaku-lab.org](https://riverdoc.kohaku-lab.org)**

- **使用者指南** — 安裝、設定、任務、VPS、CLI 參考、管理
- **開發者指南** — 架構內部、程式碼結構、慣例
- **技術報告** — 深入分析 overlay 網路、QEMU 虛擬化、tunnel 協定、認證系統

---

## 授權

本專案採用 **GNU Affero General Public License v3.0 (AGPL-3.0)** 授權。

如需商業或專有授權豁免，請聯繫：**kohaku@kblueleaf.net**
