# Ministral-8B-Instruct-2410 Deployment

Deploys [mistralai/Ministral-8B-Instruct-2410](https://huggingface.co/mistralai/Ministral-8B-Instruct-2410) on OpenShift with vLLM.

## Model Details

- **Model**: Ministral-8B-Instruct-2410
- **Size**: ~15GB (FP16)
- **GPU**: 1x NVIDIA A10G (24GB)
- **Context**: 16,384 tokens (limited from 128k for memory)
- **Features**: Function/tool calling, multilingual, code generation
- **Runtime**: vLLM v0.11.2

## Deployment

```bash
# Create namespace
oc apply -f manifests/namespace.yaml

# Optional: Create HuggingFace token secret (for gated models)
oc create secret generic hf-token --from-literal=token=hf_xxxxx -n ministral

# Deploy vLLM with Ministral-8B
oc apply -f manifests/deployment.yaml -n ministral
oc apply -f manifests/service.yaml -n ministral
oc apply -f manifests/route.yaml -n ministral

# Wait for deployment (model download takes ~5 minutes)
oc wait --for=condition=Available deployment/ministral-8b -n ministral --timeout=600s

# Verify pod is ready
oc get pods -n ministral -l app=ministral-8b
```

## Endpoint

```bash
# Get the route URL
URL=$(oc get route ministral-8b -n ministral -o jsonpath='{.spec.host}')
echo "https://${URL}"
```

Current deployment: `https://ministral-8b-ministral.apps.cluster-mqwwr.mqwwr.sandbox1259.opentlc.com`

## Testing

### Basic Completion

```bash
URL=$(oc get route ministral-8b -n ministral -o jsonpath='{.spec.host}')

curl -sk "https://${URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ministral-8b",
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "max_tokens": 50
  }'
```

### Tool/Function Calling

```bash
curl -sk "https://${URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ministral-8b",
    "messages": [{"role": "user", "content": "What is the weather in Paris?"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {"type": "string", "description": "City name"}
          },
          "required": ["location"]
        }
      }
    }],
    "max_tokens": 200
  }'
```

Expected response includes:
```json
{
  "tool_calls": [{
    "type": "function",
    "function": {
      "name": "get_weather",
      "arguments": "{\"location\": \"Paris\"}"
    }
  }]
}
```

## vLLM Configuration

Key flags for Ministral-8B (see deployment.yaml):

| Flag | Purpose |
|------|---------|
| `--tokenizer-mode=mistral` | Use Mistral tokenizer format |
| `--config-format=mistral` | Use Mistral config format |
| `--load-format=mistral` | Use Mistral weight format |
| `--enable-auto-tool-choice` | Enable automatic tool calling |
| `--tool-call-parser=mistral` | Use Mistral tool call parser |
| `--max-model-len=16384` | Limit context to fit in A10G memory |
| `--trust-remote-code` | Required for model loading |

## Resource Requirements

| Resource | Request | Limit |
|----------|---------|-------|
| CPU | 4 cores | 8 cores |
| Memory | 24Gi | 32Gi |
| GPU | 1x nvidia.com/gpu | 1x nvidia.com/gpu |

## Manifests

| File | Purpose |
|------|---------|
| `namespace.yaml` | Creates `ministral` namespace |
| `deployment.yaml` | vLLM deployment with GPU and all configuration |
| `service.yaml` | ClusterIP service on port 8080 |
| `route.yaml` | OpenShift Route with TLS edge termination |

## Troubleshooting

### Check logs
```bash
oc logs deployment/ministral-8b -n ministral --tail=50
```

### Model loading progress
Model download from HuggingFace takes ~2-3 minutes. Look for:
```
Loading safetensors checkpoint shards: 100% Completed
Loading model weights took 14.9693 GB
Application startup complete.
```

### Health check
```bash
curl -sk "https://${URL}/health"
```

## LibreChat Integration

Ministral-8B works with LibreChat agents and MCP tools, but requires specific configuration.

### LibreChat Configuration (librechat.yaml)

```yaml
endpoints:
  custom:
    - name: "Ministral-8B"
      apiKey: "dummy"  # vLLM doesn't require auth
      baseURL: "https://ministral-8b-ministral.apps.cluster-mqwwr.mqwwr.sandbox1259.opentlc.com/v1"
      models:
        default: ["ministral-8b"]
      titleConvo: true
      titleModel: "ministral-8b"
      summarize: false
      forcePrompt: false
      modelDisplayLabel: "Ministral-8B"
      dropParams:
        - "user"
        - "tool_choice"  # IMPORTANT: vLLM 0.6.6 doesn't support "required"
      addParams:
        max_tokens: 4096
```

**Key Configuration Notes:**

1. **Drop `tool_choice`**: vLLM only supports `"auto"`, `"none"`, or named tool choice. LibreChat may send `"required"` which causes errors.

2. **Drop `user`**: vLLM doesn't use the user parameter.

### MCP Tool Integration Fix

When using MCP tools with Ministral via LibreChat, a code fix is required in LibreChat's `api/server/services/MCP.js`.

**The Problem:**
MCP servers return tool results in array format:
```json
[{"type": "text", "text": "{\"temperature\": \"72°F\"}"}]
```

But vLLM expects tool content as a plain string (even in v0.11.2):
```json
"{\"temperature\": \"72°F\"}"
```

**Root Cause Analysis:**

We tested this issue across vLLM versions:
- **vLLM 0.6.6**: Rejects array format for tool content
- **vLLM 0.11.2**: Still rejects array format for tool content

The issue is that vLLM follows strict OpenAI API validation for the `ToolMessage.content` field, while OpenAI's own API is more lenient and accepts both string and array formats. This is why MCP works with OpenAI directly but fails with vLLM.

Error from vLLM 0.11.2 when sending array format:
```
Input should be a valid string [type=string_type, input_value=[{'text': 'The weather...', 'type': 'text'}], input_type=list]
```

**The Fix:**
Add this extraction logic in `MCP.js` after the Google endpoint handling:

```javascript
// For custom endpoints (vLLM/Mistral), extract text from MCP content array
// MCP returns [{type: "text", text: "..."}] but vLLM expects plain string
if (Array.isArray(result) && Array.isArray(result[0]) && result[0][0]?.type === ContentTypes.TEXT) {
  return [result[0][0].text, result[1]];
}
```

This fix has been submitted as a PR to LibreChat: [fix/mcp-custom-endpoint-content](https://github.com/danny-avila/LibreChat/pulls)

### Mistral/vLLM Constraints

| Constraint | Details |
|------------|---------|
| `tool_call_id` format | Must be exactly 9 alphanumeric characters (a-z, A-Z, 0-9). Ministral generates compliant IDs automatically. |
| `tool_choice: "required"` | Not supported. Use `"auto"` or drop the parameter. |
| Tool content format | Must be string, not array. vLLM 0.11.2 still enforces strict validation. |
| Named `tool_choice` | Causes inconsistent output. Prefer `"auto"`. |
| JSON mode | `response_format: {"type": "json_object"}` can cause repetition loops. Avoid for now. |

### Verified Capabilities

| Feature | Status |
|---------|--------|
| Basic chat completions | ✅ Working |
| Tool/function calling | ✅ Working |
| Parallel tool calls | ✅ Working |
| Multi-turn tool conversations | ✅ Working |
| Streaming responses | ✅ Working |
| MCP tool integration | ✅ Working (with fix) |

### Testing with MCP

Full end-to-end test with weather MCP server:

```bash
URL="https://ministral-8b-ministral.apps.cluster-mqwwr.mqwwr.sandbox1259.opentlc.com"

# Step 1: Model requests tool call
curl -sk "$URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ministral-8b",
    "messages": [
      {"role": "system", "content": "You are a helpful weather assistant."},
      {"role": "user", "content": "What is the weather in Seattle, WA?"}
    ],
    "tools": [{
      "type": "function",
      "function": {
        "name": "weather_current",
        "description": "Get current weather for a US location",
        "parameters": {
          "type": "object",
          "properties": {"location": {"type": "string"}},
          "required": ["location"]
        }
      }
    }],
    "max_tokens": 200
  }'

# Step 2: Send tool result back (note: tool_call_id from step 1)
curl -sk "$URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ministral-8b",
    "messages": [
      {"role": "system", "content": "You are a helpful weather assistant."},
      {"role": "user", "content": "What is the weather in Seattle, WA?"},
      {"role": "assistant", "tool_calls": [{"id": "ABC123xyz", "type": "function", "function": {"name": "weather_current", "arguments": "{\"location\": \"Seattle, WA\"}"}}]},
      {"role": "tool", "tool_call_id": "ABC123xyz", "content": "{\"temperature\":\"44°F\",\"conditions\":\"Light Rain\"}"}
    ],
    "tools": [{"type": "function", "function": {"name": "weather_current", "description": "Get current weather", "parameters": {"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}}}],
    "max_tokens": 300
  }'
```

## Deployment Notes

### Plain Deployment vs KServe

This model uses a plain Kubernetes Deployment rather than KServe InferenceService. During testing, KServe's proxy layer interfered with tool calling functionality. The plain Deployment approach provides:

- Direct access to vLLM without proxy overhead
- Reliable tool calling behavior
- Simpler debugging and log access

## References

- [Hugging Face Model Card](https://huggingface.co/mistralai/Ministral-8B-Instruct-2410)
- [vLLM Tool Calling Docs](https://docs.vllm.ai/en/stable/features/tool_calling/)
- [Red Hat AI Article](https://developers.redhat.com/articles/2025/12/02/run-mistral-large-3-ministral-3-vllm-red-hat-ai)
