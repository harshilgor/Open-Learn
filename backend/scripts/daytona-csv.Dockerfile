FROM daytonaio/sandbox:0.9.0
USER root
RUN mkdir -p /workspace/uploads /workspace/working /workspace/outputs \
    && chown -R daytona:daytona /workspace
USER daytona
