FROM mcr.microsoft.com/dotnet/sdk:10.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace/client-side-pb

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /workspace/client-side-pb/requirements.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir -r /workspace/client-side-pb/requirements.txt

COPY . /workspace/client-side-pb

CMD ["python3", "-m", "worker.worker", "--root", "/workspace/client-side-pb", "--once"]
