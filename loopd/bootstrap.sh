#!/usr/bin/env bash
# loopd/bootstrap.sh —— 沙盒环境初始化（手册 2.2④ 调用）
# 做四件事：装 gh/mise/jq → 落地 loopd.py/loop → clone product-x → 预热证据工具
set -euo pipefail

LOOP_ORG="${LOOP_ORG:?LOOP_ORG not set}"
LOOP_REPO="${LOOP_REPO:?LOOP_REPO not set}"
LOOP_WS="${LOOP_WS:?LOOP_WS not set}"
LOOP_BOOTSTRAP_REF="${LOOP_BOOTSTRAP_REF:-v0.1.0}"
RAW_BASE="https://raw.githubusercontent.com/${LOOP_ORG}/loop/${LOOP_BOOTSTRAP_REF}"

echo "=== [1/4] Install gh / mise / jq ==="
# gh：已装则跳过
if ! command -v gh >/dev/null 2>&1; then
  echo "Installing gh CLI..."
  # TODO: sha256 校验位由 loop upstream 流程现场填
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null || true
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq gh
fi
gh --version | head -1

# mise：已装则跳过
if ! command -v mise >/dev/null 2>&1; then
  echo "Installing mise..."
  # TODO: sha256 校验位由 loop upstream 流程现场填
  curl -fsSL https://mise.run | bash
  export PATH="$HOME/.local/bin:$PATH"
fi
mise --version

# jq：已装则跳过
if ! command -v jq >/dev/null 2>&1; then
  sudo apt-get install -y -qq jq
fi
jq --version

echo "=== [2/4] Deploy loopd.py + loop shim to /usr/local/bin ==="
# 拉 loopd.py 与 loop shim
for f in loopd.py loop; do
  python3 -c "import urllib.request; urllib.request.urlretrieve('${RAW_BASE}/loopd/${f}', '/tmp/${f}')"
  # TODO: sha256 校验位由 loop upstream 流程现场填
  sudo install -m 0755 "/tmp/${f}" "/usr/local/bin/${f}"
done
echo "loopd.py -> $(python3 -c 'import loopd; print(loopd.__file__)' 2>/dev/null || echo /usr/local/bin/loopd.py)"
echo "loop -> $(which loop)"

echo "=== [3/4] Clone ${LOOP_REPO} to ${LOOP_WS} ==="
if [ -d "${LOOP_WS}/.git" ]; then
  echo "Workspace exists, calibrating remote..."
  cd "${LOOP_WS}"
  git remote set-url origin "https://github.com/${LOOP_ORG}/${LOOP_REPO}.git"
  git fetch origin --prune
else
  git clone "https://github.com/${LOOP_ORG}/${LOOP_REPO}.git" "${LOOP_WS}"
  cd "${LOOP_WS}"
fi
# 对齐 .tool-versions
if [ -f ".tool-versions" ]; then
  mise install
fi

echo "=== [4/4] Pre-warm evidence tools ==="
# 每个工具：已装则跳过；二进制 sha256 校验位留 TODO，由 loop upstream 流程现场填
install_tool() {
  local name="$1" url="$2"
  if command -v "${name}" >/dev/null 2>&1; then
    echo "${name}: already installed"
    return
  fi
  echo "Installing ${name}..."
  # TODO: sha256=$(curl -fsSL ${url}.sha256) ; verify after download
  local tmpbin="/tmp/${name}"
  python3 -c "import urllib.request; urllib.request.urlretrieve('${url}', '${tmpbin}')" || {
    echo "WARNING: ${name} download failed, skipping (will retry on first use)"
    return
  }
  chmod +x "${tmpbin}" && sudo mv "${tmpbin}" "/usr/local/bin/${name}"
}

# zizmor (pip)
if ! command -v zizmor >/dev/null 2>&1; then
  pip install zizmor 2>/dev/null || echo "WARNING: zizmor install failed"
fi

# gitleaks
install_tool gitleaks "https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks-linux-amd64"

# osv-scanner
install_tool osv-scanner "https://github.com/google/osv-scanner/releases/latest/download/osv-scanner-linux-amd64"

# syft
install_tool syft "https://github.com/anchore/syft/releases/latest/download/syft-linux-amd64"

# grype
install_tool grype "https://github.com/anchore/grype/releases/latest/download/grype-linux-amd64"

echo "=== bootstrap.sh complete ==="
