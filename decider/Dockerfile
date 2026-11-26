# GPU (SageMaker): docker build decider/
# CPU (local):     docker build --build-arg BASE=python:3.12-slim --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cpu decider/
ARG BASE=pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime
FROM ${BASE}
ARG TORCH_INDEX=
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN if [ -n "$TORCH_INDEX" ]; then pip install --index-url "$TORCH_INDEX" torch torchvision; fi
COPY requirements.txt /app/decider/requirements.txt
RUN pip install -r /app/decider/requirements.txt
COPY . /app/decider
RUN chmod +x /app/decider/serve && ln -sf /app/decider/serve /usr/local/bin/serve
WORKDIR /app
EXPOSE 8080
CMD ["serve"]
