# KohakuRiver - 小型團隊的輕量叢集管理工具

[![授權條款: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![en](https://img.shields.io/badge/lang-en-red.svg)](./README.md)
[![中文](https://img.shields.io/badge/lang-中文-green.svg)](./README.zh.md)

![KohakuRiver logo svg](image/logo.svg)

**KohakuRiver** 是一套輕量、可自架的叢集管理系統，專門用於在多個運算節點間分配命令列任務，以及啟動持久性互動式工作階段（**VPS 任務**）。它善用 **Docker** 來管理可重現的任務環境，讓容器成為可攜式的「虛擬環境」，並在叢集間自動同步。

系統提供資源分配（CPU/記憶體/GPU 限制）、多節點/NUMA/GPU 任務提交，以及狀態追蹤等功能。對於研究實驗室、中小型團隊、家用實驗室，或是需要簡單、可重現的分散式任務執行環境來說，這是個理想的選擇——不必承擔複雜 HPC 排程器帶來的維運負擔。

## 核心特色

| 特色 | 說明 |
|------|------|
| **容器即可攜環境** | Docker 容器作為自動同步的虛擬環境。在 Host 設定一次、打包成 tarball，所有節點就能自動使用。 |
| **Task/VPS 雙模式** | **Task** 用於批次命令執行，**VPS** 用於持久性互動式工作階段。VPS 對研發流程特別重要——因為你沒辦法事先建好完整的 Docker image。 |
| **TTY 轉發** | 透過 WebSocket 的終端機連線（`kohakuriver connect`），不需要 Docker port mapping。支援完整 TTY（vim、htop 都能用），系統重啟後依然可用。 |
| **Port 轉發** | 透過 tunnel proxy 進行動態 port 轉發（`kohakuriver forward`）。存取容器服務不需要 Docker port mapping，避免 runner 節點上的 port 衝突。 |
| **Web UI 與終端機 TUI** | Web 儀表板提供視覺化管理，終端機 TUI（`kohakuriver terminal`）有類似 VSCode 的佈局，還有帶檔案樹和整合終端機的 IDE 模式。 |

## KohakuRiver 是什麼？

### 痛點

研究人員和小型團隊在使用少量運算節點（通常 3-8 台機器）時，常常陷入尷尬的處境：

- **機器太多**，用 SSH 和 shell script 手動管理太累
- **機器太少**，部署 Slurm 這類複雜 HPC 排程器又太浪費
- **容器編排系統**（像 Kubernetes）對於簡單的任務分發或單一長時間執行的互動式工作來說**太過頭了**

你手上有這些強大的運算資源，卻找不到一個有效率的方法，能在不增加大量維運負擔的情況下，把它們當成一整塊運算資源來用。

### 核心理念：把所有節點當成一台大電腦

KohakuRiver 用以下設計原則來解決這個問題，讓你把小型叢集當成一台強大的電腦來使用：

- **輕量資源管理**：用最少的設定，在節點間分發命令列任務和互動式 VPS 工作階段
- **環境一致性**：Docker 容器作為可攜式虛擬環境，而非複雜的應用程式部署
- **無縫同步**：自動把容器環境分發到 Runner 節點，不用在每個節點上手動設定
- **熟悉的工作流程**：透過簡單介面提交任務，感覺就像在本機執行命令或啟動環境一樣

> KohakuRiver 裡的 Docker 就像一個可以動態調整、自動同步的虛擬環境。你可以用同一個容器環境執行幾十個任務或啟動多個互動式工作階段，但讓它們在完全不同的節點上跑。

### 運作方式

1. **環境管理**：用 `kohakuriver docker container` 指令和互動式 shell，在 Host 節點上建立和自訂 Docker 容器。
2. **打包與分發**：用 `kohakuriver docker tar create` 把環境打包成 tarball，存到共享儲存空間。
3. **自動同步**：Runner 節點在執行任務前，會自動從共享儲存空間抓取需要的環境。
4. **平行/互動式執行**：提交單一命令、批次平行任務，或啟動持久性 VPS 任務在多個節點上執行，每個任務都隔離在自己的容器實例中。

這種做法符合以下理念：

> 對於小型本地叢集，應該優先選擇「輕量、簡單、剛剛好」的方案。你不需要把每個命令都打包成複雜的 Dockerfile——Docker 在這裡的用途是環境管理和同步。

KohakuRiver 假設在小型本地叢集中：

- 節點之間可以輕鬆建立網路通訊
- 共享儲存空間隨時可用
- 不需要認證系統，或認證的複雜度可以降到最低
- 在這個規模下，高可用性和容錯能力並非首要考量

透過專注於小規模運算的實際需求，KohakuRiver 提供了多節點任務執行和互動式環境的「剛剛好」方案，不會帶來企業級系統的管理負擔。

---

## KohakuRiver 適合與不適合的場景

| KohakuRiver 適合... | KohakuRiver 不適合... |
|:---|:---|
| ✅ 管理小型叢集中的命令列任務/腳本和持久性 VPS 工作階段（通常 < 10-20 節點） | ❌ 取代大型叢集上功能豐富的 HPC 排程器（Slurm、PBS、LSF） |
| ✅ **在 KohakuRiver 管理的可重現 Docker 容器環境中執行任務和 VPS 工作階段** | ❌ 編排複雜的多服務應用程式（像 Kubernetes 或 Docker Compose） |
| ✅ **在 Host 上互動式設定環境，並打包成可攜式 tarball 進行分發** | ❌ 自動管理容器*內部*的複雜軟體相依性（使用者透過 Host 的 shell 自己設定） |
| ✅ **方便地在節點/NUMA 區域/GPU 上提交獨立命令列任務、批次平行任務或單一 VPS 工作階段** | ❌ 複雜的任務相依性管理或工作流程編排（請用 Airflow、Prefect、Snakemake、Nextflow） |
| ✅ 提供有 SSH 存取的隨需互動式運算環境（VPS 任務） | ❌ 提供高可用、負載平衡的生產*服務*供外部使用者直接存取 |
| ✅ 個人、研究實驗室、小型團隊或家用實驗室需要*簡單*的多節點任務/VPS 管理系統 | ❌ 部署或管理高可用、任務關鍵型的生產*服務* |
| ✅ 提供輕量系統，在受控環境中進行分散式任務執行，維護負擔最小 | ❌ 需要完整認證和授權機制的高安全性、多租戶環境 |

---

## 功能特色

### 容器環境管理
- **託管式 Docker 工作流程**：在 Host 建立容器（`kohakuriver docker container create`）、互動式自訂（`kohakuriver docker container shell`）、打包成 tarball（`kohakuriver docker tar create`）。
- **自動同步**：Runner 在執行任務前會自動從共享儲存空間抓取並更新容器 tarball。

### 任務執行
- **Command Task**：在 Docker 容器中一次性執行命令，可設定資源限制。
- **VPS Task**：帶 SSH 存取的持久性互動式容器——研發流程的好夥伴，讓你可以邊開發邊調整環境。
- **多目標提交**：一個指令就能把任務提交到多個節點/NUMA 節點/GPU。

### 存取與連線（不需要 Docker Port Mapping）
- **TTY 轉發（`kohakuriver connect`）**：WebSocket 終端機，完整 TTY 支援（vim、htop 都能用）。長時間執行的容器在系統重啟後依然可以連線。
- **Port 轉發（`kohakuriver forward`）**：透過 tunnel proxy 的動態 TCP/UDP port 轉發。存取容器服務（web server、資料庫、Jupyter）不會有 port 衝突。
- **SSH Proxy**：透過 Host 中繼用 SSH 連到 VPS（`kohakuriver vps connect`），不需要知道 runner IP 或動態 port。

### 資源管理
- **CPU/記憶體分配**：指定核心數（`-c/--cores`）和記憶體限制（`-m/--memory`）。
- **GPU 分配**：指定 GPU（`--target node::gpu_id1,gpu_id2`）。
- **NUMA 綁定**：把任務綁定到 NUMA 節點（`--target node:numa_id`）。

### 監控與介面
- **Web 儀表板**：Vue.js 前端，有叢集總覽、任務/VPS 提交、Docker 管理、網頁終端機。
- **終端機 TUI（`kohakuriver terminal`）**：全螢幕儀表板，顯示節點狀態、任務列表，支援鍵盤操作。
- **IDE 模式（`kohakuriver connect --ide`）**：TUI IDE，有檔案樹、程式碼編輯器和整合終端機面板。
- **任務控制**：透過 CLI 或 Web UI 暫停、恢復、終止任務。

---

## 快速入門

### 前置需求

- Python >= 3.10
- Host 和所有 Runner 節點都能存取的共享檔案系統
- **Host 節點**：已安裝 Docker Engine（用於管理環境和建立 tarball）
- **Runner 節點**：已安裝 Docker Engine（用於執行容器化任務和 VPS）。`numactl` 選用（只有 NUMA 綁定功能需要）。`nvidia-ml-py` 和 NVIDIA 驅動選用（只有 GPU 回報/分配需要）
- **Client 機器**：已安裝 SSH client（`ssh` 指令）
- **Docker Engine**：確保 data-root 和 storage driver 設定正確。跑 `docker run hello-world` 確認 Docker 正常運作

### 步驟

1. **安裝 KohakuRiver**（在 Host、所有 Runner 節點和 Client 機器上）：

   ```bash
   # Clone repo
   git clone https://github.com/KohakuBlueleaf/KohakuRiver.git
   cd KohakuRiver

   # 安裝
   pip install .

   # 要 GPU 監控支援的話（需要 nvidia-ml-py 和 nvidia 驅動）
   pip install ".[gpu]"
   ```

2. **設定 KohakuRiver**（在 Host、所有 Runner 和 Client 機器上）：

   ```bash
   # 產生預設設定檔
   kohakuriver init config --generate
   ```

   編輯設定檔：
   - **Host 設定**（`~/.kohakuriver/host_config.py`）：
     - **重要**：把 `HOST_REACHABLE_ADDRESS` 設成 Runner/Client 可以連到的 Host IP/主機名稱
     - **重要**：把 `SHARED_DIR` 設成你的共享儲存路徑（例如 `/mnt/cluster-share`）
   - **Runner 設定**（`~/.kohakuriver/runner_config.py`）：
     - **重要**：把 `HOST_ADDRESS` 設成 Host 的 IP/主機名稱
     - **重要**：把 `SHARED_DIR` 設成一樣的共享儲存路徑

3. **啟動 Host 伺服器**（在管理節點上）：

   ```bash
   kohakuriver.host
   # 或用特定設定檔：kohakuriver.host --config /path/to/host_config.py
   ```

   **用 Systemd（正式環境建議）：**
   ```bash
   kohakuriver init service --host
   sudo systemctl start kohakuriver-host
   sudo systemctl enable kohakuriver-host
   ```

4. **啟動 Runner Agent**（在每個運算節點上）：

   ```bash
   kohakuriver.runner
   # 或用特定設定檔：kohakuriver.runner --config /path/to/runner_config.py
   ```

   **用 Systemd：**
   ```bash
   kohakuriver init service --runner
   sudo systemctl start kohakuriver-runner
   sudo systemctl enable kohakuriver-runner
   ```

5. **（選用）準備 Docker 環境**（在 Client/Host 上）：

   ```bash
   # 在 Host 建立基礎容器
   kohakuriver docker container create python:3.12-slim my-py312-env

   # 互動式安裝軟體
   kohakuriver docker container shell my-py312-env
   # （容器裡）pip install numpy pandas torch
   # （容器裡）exit

   # 打包成 tarball
   kohakuriver docker tar create my-py312-env
   ```

6. **提交第一個任務**（從 Client 機器）：

   ```bash
   # 用預設 Docker 環境在 node1 提交簡單的 echo 指令
   kohakuriver task submit -t node1 -- echo "Hello KohakuRiver!"

   # 用自訂環境在 node2 以 2 核心跑 Python 腳本
   # （假設 myscript.py 在共享目錄，可透過 /shared 存取）
   kohakuriver task submit -t node2 -c 2 --container my-py312-env -- python /shared/myscript.py

   # 在 node3 用 GPU 0 和 1 提交 GPU 任務
   kohakuriver task submit -t node3::0,1 --container my-cuda-env -- python /shared/train_gpu_model.py
   ```

7. **啟動 VPS 任務**（從 Client 機器）：

   ```bash
   # 建立 4 核心、8GB 記憶體的 VPS
   kohakuriver vps create -t node1 -c 4 -m 8G

   # 透過 SSH proxy 連線
   kohakuriver vps connect <task_id>

   # 或用 WebSocket 終端機（不需要 Docker port mapping）
   kohakuriver connect <task_id>

   # 或開啟帶檔案樹和終端機的 TUI IDE
   kohakuriver connect <task_id> --ide
   ```

8. **轉發 Port 到容器服務**（不需要 Docker port mapping）：

   ```bash
   # 轉發本機 port 8888 到容器的 Jupyter（port 8888）
   kohakuriver forward <task_id> 8888

   # 轉發本機 port 3000 到容器的 port 80
   kohakuriver forward <task_id> 80 --local-port 3000

   # 轉發 UDP
   kohakuriver forward <task_id> 5353 --proto udp
   ```

9. **使用終端機 TUI 儀表板**：

   ```bash
   # 啟動全螢幕儀表板
   kohakuriver terminal
   ```

---

## 架構

```
┌─────────────────────────────────────────────────────────────┐
│  Clients: CLI / Web Dashboard / Terminal TUI                │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP/WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│  HOST SERVER (Port 8000)                                    │
│  - 任務排程與分派                                           │
│  - 節點註冊與健康監控                                       │
│  - Docker 環境管理                                          │
│  - VPS 存取的 SSH proxy (Port 8002)                         │
│  - 終端機和 port 轉發的 WebSocket proxy                     │
│  - SQLite 資料庫儲存狀態                                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  RUNNER 1       │ │  RUNNER 2       │ │  RUNNER N       │
│  Port 8001      │ │  Port 8001      │ │  Port 8001      │
│  - 任務執行     │ │  - 任務執行     │ │  - 任務執行     │
│  - VPS 管理     │ │  - VPS 管理     │ │  - VPS 管理     │
│  - 資源監控     │ │  - 資源監控     │ │  - 資源監控     │
│  - Tunnel 服務  │ │  - Tunnel 服務  │ │  - Tunnel 服務  │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                 │                 │
         ▼                 ▼                 ▼
    ┌─────────┐       ┌─────────┐       ┌─────────┐
    │Container│       │Container│       │Container│
    │(tunnel- │       │(tunnel- │       │(tunnel- │
    │ client) │       │ client) │       │ client) │
    └─────────┘       └─────────┘       └─────────┘

┌─────────────────────────────────────────────────────────────┐
│  SHARED STORAGE (/mnt/cluster-share)                        │
│  - kohakuriver-containers/  (Docker tarball)                │
│  - shared_data/             (在任務中掛載為 /shared)        │
└─────────────────────────────────────────────────────────────┘
```

### TTY 與 Port 轉發架構

Tunnel 系統讓你不需要 Docker port mapping 就能存取容器服務：

```
使用者/應用程式
        │
        ▼ TCP/UDP（Port 轉發用）
kohakuriver connect/forward
        │
        ▼ WebSocket
   HOST (proxy) ------> RUNNER (tunnel server) ------> Container
                                                        (tunnel-client)
                                                            │
                                                            ▼ TCP/UDP（Port 轉發用）
                                                      容器內的服務
```

這個設計讓你能夠：
- 長時間執行的容器在系統重啟後依然可用
- 多個容器可以用同一個 port（不會衝突）
- 透過 Host 安全存取，不用直接暴露 runner 節點

---

## CLI 參考

### 任務管理
```bash
kohakuriver task list                      # 列出所有任務
kohakuriver task submit [OPTIONS] -- CMD   # 提交命令任務
kohakuriver task status <task_id>          # 取得任務狀態
kohakuriver task logs <task_id>            # 看任務輸出
kohakuriver task kill <task_id>            # 終止執行中的任務
kohakuriver task pause <task_id>           # 暫停任務
kohakuriver task resume <task_id>          # 恢復暫停的任務
```

### VPS 管理
```bash
kohakuriver vps list                       # 列出 VPS 實例
kohakuriver vps create [OPTIONS]           # 建立 VPS
kohakuriver vps stop <task_id>             # 停止 VPS
kohakuriver vps connect <task_id>          # 透過 proxy SSH 到 VPS
kohakuriver vps restart <task_id>          # 重啟 VPS
```

### 終端機與 Port 存取
```bash
kohakuriver connect <task_id>              # WebSocket 終端機（完整 TTY）
kohakuriver connect <task_id> --ide        # TUI IDE，有檔案樹和終端機
kohakuriver forward <task_id> <port>       # 轉發本機 port 到容器
kohakuriver forward <task_id> <port> -l <local_port>  # 自訂本機 port
kohakuriver forward <task_id> <port> --proto udp      # UDP 轉發
kohakuriver terminal                       # 啟動終端機 TUI 儀表板
```

### 節點管理
```bash
kohakuriver node list                      # 列出已註冊的節點
kohakuriver status                         # 快速叢集總覽
```

### Docker 管理
```bash
kohakuriver docker container list          # 列出 Host 容器
kohakuriver docker container create IMG NAME  # 從 image 建立容器
kohakuriver docker container shell NAME    # 進入容器 shell
kohakuriver docker container start NAME    # 啟動容器
kohakuriver docker container stop NAME     # 停止容器
kohakuriver docker container delete NAME   # 刪除容器
kohakuriver docker tar list                # 列出 tarball
kohakuriver docker tar create NAME         # 從容器建立 tarball
kohakuriver docker tar delete NAME         # 刪除 tarball
```

### 設定
```bash
kohakuriver init config --all              # 產生所有設定檔
kohakuriver init config --host             # 只產生 host 設定
kohakuriver init config --runner           # 只產生 runner 設定
kohakuriver init service --all             # 註冊所有 systemd 服務
kohakuriver init service --host            # 註冊 host 服務
kohakuriver init service --runner          # 註冊 runner 服務
```

---

## 設定

設定檔用 Python 搭配 KohakuEngine。如果存在，會自動從 `~/.kohakuriver/` 載入。

### Host 設定（`~/.kohakuriver/host_config.py`）

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `HOST_BIND_IP` | str | `"0.0.0.0"` | Host 伺服器綁定的 IP |
| `HOST_PORT` | int | `8000` | API 伺服器 port |
| `HOST_SSH_PROXY_PORT` | int | `8002` | VPS 存取的 SSH proxy port |
| `HOST_REACHABLE_ADDRESS` | str | `"127.0.0.1"` | **重要**：Runner 用來連到 Host 的 IP/主機名稱 |
| `SHARED_DIR` | str | `"/mnt/cluster-share"` | 共享儲存路徑（所有節點要一樣） |
| `DB_FILE` | str | `"/var/lib/kohakuriver/kohakuriver.db"` | SQLite 資料庫路徑 |
| `DEFAULT_CONTAINER_NAME` | str | `"kohakuriver-base"` | 任務的預設環境 |

### Runner 設定（`~/.kohakuriver/runner_config.py`）

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `RUNNER_BIND_IP` | str | `"0.0.0.0"` | Runner 綁定的 IP |
| `RUNNER_PORT` | int | `8001` | Runner API port |
| `HOST_ADDRESS` | str | `"127.0.0.1"` | **重要**：Host 伺服器位址 |
| `HOST_PORT` | int | `8000` | Host 伺服器 port |
| `SHARED_DIR` | str | `"/mnt/cluster-share"` | 共享儲存路徑（要和 Host 一樣） |
| `LOCAL_TEMP_DIR` | str | `"/tmp/kohakuriver"` | 本機暫存目錄 |

### 環境變數

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `KOHAKURIVER_HOST` | Host 伺服器位址 | `localhost` |
| `KOHAKURIVER_PORT` | Host 伺服器 port | `8000` |
| `KOHAKURIVER_SSH_PROXY_PORT` | SSH proxy port | `8002` |
| `KOHAKURIVER_SHARED_DIR` | 共享儲存路徑 | `/mnt/cluster-share` |

---

## Web 儀表板

Vue.js 前端提供：
- 叢集總覽，包含節點狀態和資源監控
- 任務提交，可選擇目標和設定資源
- VPS 建立，包含 SSH 金鑰管理
- Docker 環境管理（容器和 tarball）
- 容器和任務的網頁終端機
- GPU 使用率監控

```bash
cd src/kohakuriver-manager
npm install
npm run dev
```

---

## 需求摘要

| 元件 | 需求 |
|------|------|
| **Host 節點** | Docker Engine、Python >= 3.10、共享儲存存取權限 |
| **Runner 節點** | Docker Engine、Python >= 3.10、共享儲存存取權限、選用：`numactl`、`nvidia-ml-py` |
| **Client 機器** | Python >= 3.10、SSH client |
| **共享儲存** | NFS 或類似方案、所有節點相同掛載路徑、讀寫權限 |

---

## 授權

本專案採用 **GNU Affero General Public License v3.0 (AGPL-3.0)** 授權。

如需商業或專有用途的授權豁免，請聯繫：**kohaku@kblueleaf.net**
