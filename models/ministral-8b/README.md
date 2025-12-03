# Ministral-8B-Instruct-2410 Deployment

Deploys [mistralai/Ministral-8B-Instruct-2410](https://huggingface.co/mistralai/Ministral-8B-Instruct-2410) on OpenShift with vLLM.

## Model Details

- **Model**: Ministral-8B-Instruct-2410
- **Size**: ~15GB (FP16)
- **GPU**: 1x NVIDIA A10G (24GB)
- **Context**: 16,384 tokens (limited from 128k for memory)
- **Features**: Function/tool calling, multilingual, code generation
- **Runtime**: vLLM v0.6.6

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

## References

- [Hugging Face Model Card](https://huggingface.co/mistralai/Ministral-8B-Instruct-2410)
- [vLLM Tool Calling Docs](https://docs.vllm.ai/en/stable/features/tool_calling/)
- [Red Hat AI Article](https://developers.redhat.com/articles/2025/12/02/run-mistral-large-3-ministral-3-vllm-red-hat-ai)
