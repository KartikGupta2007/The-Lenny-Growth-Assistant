# Ollama serving the embedding model only.
#
# Generation in production is Claude: llama3.1:8b needs ~6GB resident and would
# not fit alongside this on a 2GB instance, and CPU-only inference would exceed
# OLLAMA_TIMEOUT_SECONDS anyway. Only nomic-embed-text lives here, because query
# embedding has to happen on every question.
#
# Deploy this as a Render *private* service -- Ollama has no authentication and
# must not be reachable from the internet.
FROM ollama/ollama:latest

# Bake the model into the image so a cold start does not re-pull 274MB.
#
# The server has to be running for `ollama pull` to work, but it never exits on
# its own -- and BuildKit will not finish a layer while a child still holds the
# build's stdout. So: redirect its output to a file, remember its pid, pull, then
# kill it and return the pull's own exit status so a failed pull fails the build.
RUN ollama serve > /tmp/ollama-build.log 2>&1 & \
    pid=$!; \
    for _ in $(seq 1 60); do ollama list > /dev/null 2>&1 && break; sleep 1; done; \
    ollama pull nomic-embed-text; status=$?; \
    kill "$pid" 2>/dev/null || true; \
    wait "$pid" 2>/dev/null || true; \
    exit $status

# Keep the model resident: the default 5-minute unload would make the first
# question after a lull pay the load cost again.
ENV OLLAMA_KEEP_ALIVE=-1
ENV OLLAMA_MAX_LOADED_MODELS=1

COPY start.sh /start.sh
RUN chmod +x /start.sh

# The base image's entrypoint ignores $PORT, which Render injects.
ENTRYPOINT []
CMD ["/start.sh"]
