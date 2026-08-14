# Yunxiao Docker execution boundary

Date: 2026-08-14

## Live evidence

- CI-only run 4 cloned the expected Codeup commit but the deprecated/default build environment had
  no `docker` executable.
- Commit `e225ebdc7474e5e60c7939f8bc87208e06ca6a81` moved the two Docker-dependent jobs to the exact
  linux/amd64 digest of Yunxiao's official alinux3 specified container.
- CI-only run 6 cloned that exact commit. Docker CLI and Compose v2 were present, while the injected
  local Docker endpoint was unreachable. The first redacted `docker info` probe failed, so no
  dependency install, application image build, ACR push, backup, Runner, provider, WeCom, or
  production action occurred.

## Official contract review

- [Build clusters](https://help.aliyun.com/zh/yunxiao/user-guide/build-a-cluster) documents public,
  managed VPC, and private build clusters. A private cluster uses a user-provided host and supports
  a manually enrolled non-Alibaba Linux node; managed VPC capacity is a separately created and
  billed choice.
- [Pipeline cache](https://help.aliyun.com/zh/yunxiao/user-guide/pipeline-cache) states that public
  image-build tasks receive a temporary `buildkitd` sidecar, while private build-cluster image
  tasks mount the host Docker daemon.
- [Pipeline Runner](https://help.aliyun.com/zh/yunxiao/user-guide/pipeline-runner) states that the
  private Runner enrollment command is created in the console, installed as a system service, and
  requires administrator/root authority on Linux.
- The official `DockerBuildPush` step source calls `waitDockerDaemonReady`, creates a buildx builder,
  and constructs `docker buildx build ... --push`. It is a push step, not a local Compose-service
  facility, and no reviewed contract promises its temporary sidecar to later ordinary commands.

## Decision

The project will not weaken real PostgreSQL/MinIO tests, remove offline runtime probes, download
mutable Docker tooling during a run, or use the production server as a CI builder. The accepted
next step is a separate private build-cluster Linux node in default VM mode with a healthy Docker
daemon and Compose plugin. A managed VPC build cluster is acceptable only after an administrator
explicitly accepts its resource and billing implications.

Until that node and its build-group ID are available, pipeline `5202972` remains CI-only and
failed closed, and all ACR/GitHub-backup/production flags remain false.
