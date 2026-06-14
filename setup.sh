#!/usr/bin/env bash
# setup.sh — get the Pi × Mem0 demo running from a clean machine.
set -euo pipefail

find_pi_bin() {
  if command -v pi >/dev/null 2>&1; then
    command -v pi
  elif [ -x "$HOME/.agentone/node/bin/pi" ]; then
    echo "$HOME/.agentone/node/bin/pi"
  fi
}

echo "==> 1/5  Checking the Pi binary"
PI_CMD=$(find_pi_bin || true)
if [ -z "$PI_CMD" ]; then
  echo "    Pi not found. Installing…"
  curl -fsSL https://pi.dev/install.sh | sh
  PI_CMD=$(find_pi_bin || true)
  echo "    (You may need to restart your shell or add Pi to PATH.)"
else
  echo "    Pi found: $PI_CMD"
fi

echo "==> 2/5  Installing the Mem0 plugin for Pi"
"${PI_CMD:-pi}" install npm:@mem0/pi-agent-plugin || {
  echo "    Could not auto-install the plugin. Install it manually with:"
  echo "      pi install npm:@mem0/pi-agent-plugin"
}

echo "==> 3/5  Python dependencies"
pip install -r requirements.txt

echo "==> 4/5  Mem0 environment"
if [ -z "${MEM0_API_KEY:-}" ]; then
  echo "    MEM0_API_KEY is not set. Get one at https://app.mem0.ai/dashboard/api-keys"
  echo "    Then: export MEM0_API_KEY=\"m0-...\""
else
  echo "    MEM0_API_KEY is set."
fi

echo "==> 5/5  Pi model provider"
if [ -n "${GEMINI_API_KEY:-}${OPENAI_API_KEY:-}${ANTHROPIC_API_KEY:-}${OPENROUTER_API_KEY:-}${AI_GATEWAY_API_KEY:-}${AZURE_OPENAI_API_KEY:-}" ] \
   || { [ -s "${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/auth.json" ] \
        && ! grep -q '^[[:space:]]*{}[[:space:]]*$' "${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/auth.json" 2>/dev/null; }; then
  echo "    Pi model auth is present."
else
  echo "    Pi still needs a model provider. MEM0_API_KEY is only for memory."
  echo "    Choose one:"
  echo "      pi                         # then type /login"
  echo "      export GEMINI_API_KEY=\"...\" # default provider"
  echo "      export OPENAI_API_KEY=\"...\" # then use --model openai/gpt-4o-mini"
  echo "      export AZURE_OPENAI_API_KEY=\"...\" AZURE_OPENAI_ENDPOINT=\"https://your-resource.openai.azure.com\""
  echo "      export AZURE_OPENAI_DEPLOYMENT=\"gpt-5-mini\""
  echo "                                  # then use --provider azure-openai-responses"
fi

echo
echo "All set. Launch the demo with:"
echo "    streamlit run app.py"
