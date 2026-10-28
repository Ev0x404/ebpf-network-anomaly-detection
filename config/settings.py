from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SRC_DIR = PROJECT_ROOT / "src"
TRAINING_DIR = PROJECT_ROOT / "training"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
EBPF_DIR = PROJECT_ROOT / "ebpf"
MODELS_DIR = PROJECT_ROOT / "models"
LOGS_DIR = PROJECT_ROOT / "logs"
DOCS_DIR = PROJECT_ROOT / "docs"

MODEL_FILE = MODELS_DIR / "model.pkl"
SCALER_FILE = MODELS_DIR / "scaler.pkl"
THRESHOLD_FILE = MODELS_DIR / "threshold.json"
NORMAL_TRAFFIC_FILE = MODELS_DIR / "normal_traffic.json"

ALERTS_LOG = LOGS_DIR / "alerts_local.jsonl"
GECKODRIVER_LOG = LOGS_DIR / "geckodriver.log"

N8N_WEBHOOK = "http://localhost:5678/webhook/ebpf-alert"
DOCKER_NETWORK = "ebpf-net"
N8N_CONTAINER = "n8n"
OLLAMA_CONTAINER = "ollama"
OLLAMA_MODEL = "gemma3:4b"
N8N_PORT = 5678
OLLAMA_API_URL = "http://ollama:11434/api/generate"

XDP_OBJECT = EBPF_DIR / "xdp_monitor.bpf.o"
N8N_BOOTSTRAP_WORKFLOW = SCRIPTS_DIR / "n8n_workflow.json"

for _dir in (MODELS_DIR, LOGS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
