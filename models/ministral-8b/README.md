# Ministral-8B-Instruct-2410 Deployment

Deploys [mistralai/Ministral-8B-Instruct-2410](https://huggingface.co/mistralai/Ministral-8B-Instruct-2410) on OpenShift with vLLM.

## Model Details

- **Model**: Ministral-8B-Instruct-2410
- **Size**: ~16GB (BF16)
- **GPU**: 1x NVIDIA A10G (24GB)
- **Context**: 16k tokens (limited from 128k for memory)
- **Features**: Function calling, multilingual, code

## Deployment

```bash
# Create namespace
oc apply -f manifests/namespace.yaml

# Optional: Create HuggingFace token secret (for gated models)
oc create secret generic hf-token --from-literal=token=hf_xxxxx -n ministral

# Deploy runtime and inference service
oc apply -f manifests/serving-runtime.yaml -n ministral
oc apply -f manifests/inference-service.yaml -n ministral

# Wait for deployment
oc wait --for=condition=Ready inferenceservice/ministral-8b -n ministral --timeout=600s
```

## Testing

### Basic Completion

```bash
URL=$(oc get route ministral-8b -n ministral -o jsonpath='{.spec.host}')

curl -sk "https://${URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ministral-8b",
    "messages": [{"role": "user", "content": "What is 2+2?"}]
  }'
```

### Tool Calling

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
    }]
  }'
```

## vLLM Configuration

Key flags for Ministral-8B:
- `--tokenizer-mode=mistral` - Use Mistral tokenizer
- `--config-format=mistral` - Use Mistral config format
- `--load-format=mistral` - Use Mistral weight format
- `--enable-auto-tool-choice` - Enable tool calling
- `--tool-call-parser=mistral` - Use Mistral tool parser

## References

- [Hugging Face Model Card](https://huggingface.co/mistralai/Ministral-8B-Instruct-2410)
- [vLLM Tool Calling Docs](https://docs.vllm.ai/en/stable/features/tool_calling/)
- [Red Hat AI Article](https://developers.redhat.com/articles/2025/12/02/run-mistral-large-3-ministral-3-vllm-red-hat-ai)
