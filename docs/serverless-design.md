# Outfit checker: serverless AWS + Google design (arena synthesis)

## Design
| Piece | Where | Bills to |
|---|---|---|
| Page and webcam | Firebase Hosting, Spark plan | GCP free tier |
| Reflex meter | Google SigLIP2 zero-shot in the browser, Transformers.js on WebGPU (`onnx-community/siglip2-base-patch16-224-ONNX`) | nothing |
| Decision model | Strands Decider E2B v2 (Gemma 4) or d1-2B, as a SageMaker inference component on ml.g6.xlarge, min copies 0 | AWS credits |
| Front door | Lambda function URL or API Gateway HTTP API, Lambda calls `InvokeEndpoint`. HTTPS POST, one frame in flight | AWS credits |
| Pre-warm | EventBridge Scheduler or a "warm up" button sets copy count to 1 about 20 minutes before the talk | AWS credits |
| Stylist | ADK agent on Cloud Run with Gemini Flash. Receives only the decider's text answers | GCP free tier |

## Verification run in this session
On 4 CPU threads in fp32 PyTorch, 512 px frames, the app's outfit question:

| Model | Time per frame | Two cats on a sofa | Empty bedroom | Skier |
|---|---|---|---|---|
| d1-omni-600M | 1.1 to 1.8 s | level 3 (p=0.95) | level 3 (p=0.92) | level 3 |
| d1-2B | 2.8 s | level 0 (p=0.81) | level 1, p(0)=0.43 | level 3 |

- d1-omni gave every image about level 3, so it cannot do this task. That rules out running the decision model on Lambda or in the browser with d1-omni.
- d1-2B separates the images, but it needs 2.8 s on CPU. A live meter needs a GPU, which matches the Builder Center article.
- SigLIP and SigLIP2 ONNX exports for Transformers.js exist on Hugging Face.

## Still unverified
- Strands Decider E2B v2 fit in 24 GB on an L4, and its latency on images.
- SageMaker scale-from-zero time for this container, and ml.g6.xlarge price in the chosen region.
- SigLIP zero-shot agreement with the decider on outfit levels.
