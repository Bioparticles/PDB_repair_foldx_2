SERVICE_TITLE=AI tool to use FoldX to repair PDB files

PROJECT_DIR:=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
PORT=8078
SERVICE_URL=http://localhost:${PORT}

run:
	poetry ivcap run -- --port ${PORT}

REQUEST=tests/request.json
test-local:
	curl -i -X POST \
		-H "content-type: application/json" \
		-H "timeout: 600" \
		--data @${REQUEST} \
		${SERVICE_URL}

test-job:
	poetry ivcap job-exec ${REQUEST}

docker-build:
	poetry ivcap docker-build

docker-run:
	poetry ivcap docker-run -- --port ${PORT}

.PHONY: run
