# Unknowns register

Run on 2026-11-26. Each row is VERIFIED, NOT VERIFIED or INCONCLUSIVE, with its evidence.
Model numbers come from `bench/outfit_eval.py` on 4 CPU threads (no GPU in this environment).
Cloud facts come from the linked docs.

## Model results

Labelled set: 8 images with no outfit, 5 with sport or plain clothes, 9 styled fashion photos.
Pass: mean(none) < mean(plain) < mean(styled) and AUC(styled vs rest) >= 0.85.

| Model | none | plain | styled | AUC | CPU s/frame | Peak RAM | Result |
|---|---|---|---|---|---|---|---|
| Strands Decider E2B v2 (Gemma 4), bf16 | 0.67 | 1.57 | 2.95 | 1.00 | 2.52 | 5.0 GB | PASS |
| d1-2B, fp32 | 1.00 | 1.97 | 2.87 | 1.00 | 2.76 | not measured | PASS |
| SigLIP2 base zero-shot, fp32 | 0.69 | 0.66 | 3.02 | 0.97 | 0.24 | not measured | FAIL, none and plain tie |
| d1-omni-600M, fp32 | about 3 for every image | | | | 1.1 to 1.8 | | FAIL |

Caveat: every styled image is a professional fashion photo and every other image is a COCO snapshot.
A model could pass by detecting photo style instead of outfit. The real gate is webcam frames of one
person in three outfits, which needs a person in front of a camera.

## Register

| # | Unknown | Verdict | Evidence |
|---|---|---|---|
| M1 | Decider E2B v2 accepts images | VERIFIED | Ran 22 images through `images` field |
| M2 | Decider E2B v2 judges outfits although v2 is trained on text only (model card) | VERIFIED on the labelled set, INCONCLUSIVE on webcam frames | Table above |
| M3 | Decider E2B v2 fits a 24 GB L4 | INCONCLUSIVE, likely | 10.3 GB bf16 weights; 5.0 GB peak RAM on CPU; card says 24 GB GPU. Needs a GPU run |
| M4 | Decider E2B v2 image latency on L4 | INCONCLUSIVE | No GPU here. Card: 62 ms per text question on H100 |
| M5 | Scores use the full 0 to 4 range | NOT VERIFIED | Both decision models stay between about 0.2 and 3.3. The page needs a linear stretch |
| M6 | SigLIP2 in the browser can drive the meter alone | NOT VERIFIED | Ranks styled well, cannot separate no person from plain clothes |
| M7 | Decider on CPU is fast enough for a live meter | NOT VERIFIED | 2.5 s per frame |
| C1 | SageMaker scale-to-zero holds requests while at zero | NOT VERIFIED | "any attempts to invoke the endpoint will produce an error" [docs](https://docs.aws.amazon.com/sagemaker/latest/dg/endpoint-auto-scaling-zero-instances.html) |
| C2 | Scale up from zero is automatic | NOT VERIFIED | Needs a StepScaling policy and a CloudWatch alarm on `NoCapacityInvocationFailures`, plus MinInstanceCount 0. Same docs |
| C3 | Time to scale up from zero | INCONCLUSIVE | Docs say "several minutes" |
| C4 | GPU quota for ml.g6.xlarge endpoints on the account | INCONCLUSIVE | Often 0 on new accounts. Check Service Quotas now |
| C5 | ml.g6.xlarge price and region | INCONCLUSIVE | Not on the fetched pricing page. Use the Pricing Calculator |
| C6 | AWS credits cover SageMaker | VERIFIED unless the credit lists eligible services | [AWS credits terms](https://aws.amazon.com/awscredits/) |
| C7 | AWS credits cover Hugging Face endpoints via Marketplace | NOT VERIFIED | Marketplace excluded "unless authorized by us". Same page |
| C8 | Lambda function URL works with only `lambda:InvokeFunctionUrl` | NOT VERIFIED | Since Oct 2025 new URLs also need `lambda:InvokeFunction` [docs](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html) |
| C9 | Lambda request and response fit | VERIFIED | 6 MB each, frames are about 50 KB [limits](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) |
| C10 | SageMaker custom container contract | VERIFIED | Port 8080, `/ping` and `/invocations`, `/ping` must pass within 8 minutes, model answers within 60 s [docs](https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms-inference-code.html) |
| G1 | Gemini free tier keeps inputs private | NOT VERIFIED | Free tier inputs are "used to improve our products" [pricing](https://aistudio.google.com/docs/pricing). Send text only |
| G2 | Gemini free tier rate limits | INCONCLUSIVE | No longer published as a table; per project in AI Studio |
| G3 | Cloud Run runs without a billing account | NOT VERIFIED | Billing account required even inside the free tier |
| G4 | Firebase Hosting needs a billing account | NOT VERIFIED (no account needed) | Spark: 10 GB storage, 360 MB per day [pricing](https://firebase.google.com/pricing) |
| G5 | ADK deploys to Cloud Run with an API key and no Vertex AI | INCONCLUSIVE | `google-adk`, `adk deploy cloud_run` exist; key-only mode untested |

## What changes in the design

1. Decider E2B v2 is the model. It passed and it is Apache-2.0 on Gemma 4. d1-2B is the fallback.
2. A pure Lambda path exists. 5 GB peak RAM fits Lambda's 10 GB, and 2.5 s per verdict on CPU is too slow for
   the live needle but fine as a verdict every few seconds. The weights (10.3 GB) exceed the 10 GB container
   image and `/tmp` limits, so they load from EFS. SigLIP2 in the browser moves the needle between verdicts.
3. The GPU path (SageMaker scale-to-zero) needs a quota check first, a warm-up step, and a Lambda that turns
   the error at zero into a "warming up" reply.
4. The page needs a linear stretch of the 0 to 4 level onto 0 to 100.
5. The stylist must receive text only, and Cloud Run needs a billing account even at $0.
