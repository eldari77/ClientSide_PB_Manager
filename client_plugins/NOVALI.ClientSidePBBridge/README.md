# NOVALI Client-Side PB Bridge Local Plugin

Pulsar local plugin that mirrors PB shim mailbox content into local shared files
for the Docker worker.

The plugin does not execute arbitrary PB scripts and does not issue server or
Torch commands. It only stages marked mailbox requests and returns matching
worker result files.

